# ai-parrot Admin UI — decisión y diseño (2026-08-27)

## Contexto
ai-parrot solo brinda backend. A nivel corporate (TROC) existe UI propia en Svelte 5. Para adopción open-source externa falta una UI mínima de administración cuando ai-parrot corre en modo `server`, `autonomous`, dev-loop, AgentCrew, AgentsFlow, etc.

## Decisión
- **Framework: Svelte 5 + Vite, sin SvelteKit.** SPA estática con router ligero. Razones: es lo más cercano a TypeScript + HTML; la OOP es de primera clase vía clases reactivas con `$state` (patrones ya documentados en el skill `svelte5-structural`); reúso directo de Bits UI, shadcn-svelte, interfaces TS y componentes ya creados para la UI corporate. Bits UI es Svelte-only — ningún otro framework permitía ese reúso.
- **Distribución: bundle pre-compilado dentro del build de `ai-parrot-server`.** El `dist/` estático viaja en el paquete que levanta el server aiohttp; `pip install` basta, Node solo lo necesita quien desarrolle la UI.
- Descartados: Lit 3 (OOP nativa y web components embebibles, pero sin ecosistema Bits UI/shadcn), SolidJS + shadcn-solid (TS nativo pero JSX funcional, OOP de segunda clase, como Vue).

## Alcance mínimo (v1)
1. Login / sesión.
2. Creación y listado de agentes vía AgentRegistry.
3. Creación de crews con AgentCrew.
4. Ejecución de Dev Loop flow (ya existe una interfaz HTML básica funcional — migrar o embeber).

## Notas de implementación
- aiohttp sirve `dist/` como estáticos + fallback a `index.html` para el router SPA; la API JSON del server es el mismo origin (sin CORS).
- Tipos TS compartidos: generar desde Pydantic JSON Schema (mismo patrón usado para los tipos del reducer AHP en Svelte).
- Tokens ShadCN (Tailwind + variables CSS) reutilizables tal cual desde el trabajo corporate; los componentes propios sobre Bits UI se comparten como paquete o vía copy-in estilo shadcn.
- Posible evolución: compilar componentes clave como custom elements (`<svelte:options customElement>`) para embeberlos en apps ajenas.