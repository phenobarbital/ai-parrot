# WebNavigatorAgent — navegación web con el perfil real de Chrome

`webbrowsing_agent.py` define `WebNavigatorAgent`, un `Agent` que opera
sitios web a través del **catálogo de acciones** de `WebBrowsingToolkit`
(`parrot_tools.browsing`). El agente no improvisa selectores: a partir de
una petición en lenguaje natural prepara un `WebTaskRequest`
(`{site, action, data}`) y llama a `execute_web_task`, que reproduce el
guion catalogado de forma determinista.

El catálogo por defecto es `examples/webbrowsing/catalog` (sitio de prueba
[quotes.toscrape.com](https://quotes.toscrape.com)); se regenera con
`python examples/webbrowsing/seed_catalog.py`. Ver
[`examples/webbrowsing/README.md`](../../webbrowsing/README.md) para la
lista de acciones y cómo escribir nuevas.

## Requisitos

```bash
source .venv/bin/activate
uv pip install ai-parrot-tools playwright   # o selenium
playwright install chromium                  # driver por defecto
```

Necesitas una clave de proveedor LLM en el entorno (p. ej.
`GOOGLE_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`).

## Invocación

```bash
# Navegador limpio (sin perfil), headless
python examples/agents/webbrowser/webbrowsing_agent.py "dame las citas del tag love"

# Con ventana visible
HEADLESS=0 python examples/agents/webbrowser/webbrowsing_agent.py "inicia sesión en quotes"

# Contra tu perfil real de Chrome (cookies, sesiones guardadas, keyring)
CHROME_USER_DATA=~/.config/google-chrome \
CHROME_PROFILE="Profile 1" \
HEADLESS=0 \
python examples/agents/webbrowser/webbrowsing_agent.py "inicia sesión en quotes y lista la portada"
```

Variables de entorno:

| Variable | Default | Uso |
|---|---|---|
| `CHROME_USER_DATA` | *(ninguno)* | Directorio *user-data* de Chrome (`~/.config/google-chrome`, `~/Library/Application Support/Google/Chrome`, `%LOCALAPPDATA%\Google\Chrome\User Data`). Si no se define arranca un navegador sin perfil. |
| `CHROME_PROFILE` | `Default` | Carpeta de perfil dentro de `CHROME_USER_DATA` (`Default`, `Profile 1`, …). |
| `HEADLESS` | `1` | `0` para ver el navegador. |

> **Chrome bloquea el perfil en uso.** Cierra Chrome antes de ejecutar con
> `CHROME_USER_DATA`, o apunta a una copia del directorio (ver
> [Copiar el user-data dir](#copiar-el-user-data-dir-de-chrome)).

## Copiar el user-data dir de Chrome

Trabajar sobre una copia evita el bloqueo del perfil y protege tu perfil
real de cualquier cambio que haga el agente. Cierra Chrome antes de copiar
(si no, los ficheros SQLite de cookies/historial pueden quedar
inconsistentes) y excluye la caché, que pesa mucho y no aporta nada.

**Linux**

```bash
SRC="$HOME/.config/google-chrome"          # chromium: ~/.config/chromium
DST="$HOME/.config/chrome-debug"

pkill -x chrome 2>/dev/null; sleep 2       # asegúrate de que está cerrado
rsync -a --delete \
  --exclude='Singleton*' \
  --exclude='*/Cache/' --exclude='*/Code Cache/' --exclude='*/GPUCache/' \
  --exclude='*/Service Worker/CacheStorage/' --exclude='GrShaderCache/' \
  "$SRC/" "$DST/"
```

**macOS**

```bash
SRC="$HOME/Library/Application Support/Google/Chrome"
DST="$HOME/chrome-debug"

osascript -e 'quit app "Google Chrome"'; sleep 2
rsync -a --delete \
  --exclude='Singleton*' \
  --exclude='*/Cache/' --exclude='*/Code Cache/' --exclude='*/GPUCache/' \
  --exclude='*/Service Worker/CacheStorage/' --exclude='GrShaderCache/' \
  "$SRC/" "$DST/"
```

Notas:

- `Singleton*` (`SingletonLock`, `SingletonSocket`, `SingletonCookie`) son
  los ficheros de bloqueo; si se copian Chrome pensará que la copia ya está
  en uso. Si te ocurre, bórralos de `$DST`.
- Los perfiles viven dentro del directorio (`Default`, `Profile 1`, …); para
  saber cuál es cuál mira `chrome://version` (campo *Profile Path*) o
  `jq '.profile.info_cache' "$SRC/Local State"`.
- Las contraseñas y cookies están cifradas con el keyring del SO
  (`libsecret`/Keychain), ligado al usuario, no a la ruta: la copia sigue
  siendo legible **en la misma máquina y usuario**, pero no si la mueves
  a otro equipo. En macOS, Keychain puede pedir permiso la primera vez que
  el Chrome copiado acceda a "Chrome Safe Storage".
- Repite el `rsync` cuando quieras refrescar la copia con nuevas sesiones
  de tu perfil real.

Luego usa la copia tanto para este ejemplo (`CHROME_USER_DATA="$DST"`) como
para arrancar Chrome con remote debugging (`--user-data-dir="$DST"`, ver
abajo).

Uso programático:

```python
from examples.agents.webbrowser.webbrowsing_agent import WebNavigatorAgent

agent = WebNavigatorAgent(
    user_data_dir="~/.config/google-chrome",
    profile_directory="Default",
    driver_type="playwright",   # o "selenium"
    headless=False,
    llm="google:gemini-2.5-flash",
)
await agent.configure()
answer, _ = await agent.invoke("dame las citas del tag love")
await agent.close()
```

Cuando se pasa `user_data_dir`, el agente fuerza `browser_channel="chrome"`
para lanzar el Chrome del sistema (no el Chromium de Playwright): sólo así
las contraseñas cifradas con el keyring del SO son legibles.

## Chrome con remote debugging (Chrome DevTools)

AI-Parrot trae integrado un segundo camino: `parrot.bots.chrome.WebAgent`,
que habla con Chrome mediante el **Chrome DevTools Protocol** a través del
MCP server `chrome-devtools-mcp` (requiere `npx`/Node). En vez de que el
driver lance su propio navegador, el agente se **conecta a un Chrome que
ya está corriendo** con el puerto de depuración abierto — ideal para reusar
tu sesión abierta, con tus extensiones y logins.

### 1. Levantar Chrome con el puerto de depuración y tu perfil

Chrome sólo expone el puerto de depuración si se arranca con
`--remote-debugging-port` **y** un `--user-data-dir` explícito (desde
Chrome 136 rechaza la combinación con el perfil por defecto). Lo más
práctico es usar un directorio dedicado — la copia creada en
[Copiar el user-data dir](#copiar-el-user-data-dir-de-chrome), o uno
vacío en el que inicies sesión a mano:

```bash
# Linux
google-chrome \
  --remote-debugging-port=9222 \
  --user-data-dir="$HOME/.config/chrome-debug" \
  --profile-directory=Default \
  --remote-allow-origins='*' &

# macOS
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --remote-debugging-port=9222 \
  --user-data-dir="$HOME/chrome-debug" &

# Windows (PowerShell)
& "C:\Program Files\Google\Chrome\Application\chrome.exe" `
  --remote-debugging-port=9222 `
  --user-data-dir="$env:LOCALAPPDATA\chrome-debug"
```

La primera vez inicia sesión manualmente en los sitios que quieras: el
directorio conserva cookies y sesiones entre ejecuciones.

Comprueba que el endpoint responde:

```bash
curl -s http://127.0.0.1:9222/json/version
```

Si no defines `--user-data-dir` o el puerto no está levantado, el
`ChromeManager` de AI-Parrot (`parrot.mcp.chrome`) intenta lanzar un
Chrome por su cuenta con `--remote-debugging-port=<port>` (headless según
`ChromeConfig.headless`), pero **sin perfil** — por eso conviene
levantarlo tú mismo cuando quieras sesiones persistentes.

### 2. Conectar el agente

```python
import asyncio
from parrot.bots.chrome import WebAgent, ChromeConfig

async def main():
    agent = WebAgent(
        chrome_config=ChromeConfig(
            browser_url="http://127.0.0.1:9222",   # Chrome ya corriendo
            headless=False,
        ),
        llm="google:gemini-2.5-flash",
    )
    await agent.configure()          # levanta chrome-devtools-mcp y se adjunta
    result = await agent.ask("Abre quotes.toscrape.com y dime el primer autor")
    print(result.response)

asyncio.run(main())
```

`ChromeConfig` acepta además `user_data_dir`, `channel`
(`stable|beta|dev|canary`), `viewport="1920x1080"`, `executable_path`,
`isolated=True` (contexto temporal) y `auto_connect=True` (Chrome ≥ 144
descubre solo la instancia local). Cualquier bot puede añadir la misma
capacidad con `await bot.add_chrome_devtools_mcp_server(browser_url=...)`.

### 3. Selenium contra el mismo Chrome

Si prefieres `driver_type="selenium"`, `SeleniumSetup`
(`parrot_tools.scraping.driver`) acepta `debugger_address="127.0.0.1:9222"`
y se adjunta al Chrome depurable en vez de lanzar uno nuevo.

## ¿Cuál usar?

| | `WebNavigatorAgent` (este ejemplo) | `WebAgent` + Chrome DevTools |
|---|---|---|
| Control del navegador | Playwright/Selenium lanzan Chrome | Se adjunta a un Chrome ya abierto vía CDP |
| Qué hace el LLM | Elige una acción del catálogo (determinista) | Navega libremente con tools de DevTools |
| Perfil | `user_data_dir` + `profile_directory` en el constructor | `--user-data-dir` al arrancar Chrome |
| Dependencias extra | `playwright` o `selenium` | Node/`npx` (`chrome-devtools-mcp`) |
| Ideal para | Flujos repetibles en sitios conocidos | Exploración, QA, depuración (consola, red, screenshots) |
