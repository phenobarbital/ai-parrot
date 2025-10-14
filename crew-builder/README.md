# AgentCrew Builder

AgentCrew Builder is a SvelteKit 5 application that lets you assemble, configure and export AgentCrew pipelines visually. The project now ships with Tailwind CSS v4, DaisyUI theme switching and an opinionated auth flow that persists bearer tokens in local storage.

## Features

- 🧠 **Visual crew editor** powered by [@xyflow/svelte](https://xyflow.com/) for drag-and-drop agent orchestration
- 🛠️ **Dual configuration modes** (form and JSON) with DaisyUI styling
- 🌗 **Theme switching** with DaisyUI v5 following the [Scott Spence guide](https://scottspence.com/posts/theme-switching-in-sveltekit-updated-for-daisyui-v5-and-tailwind-v4)
- 🔐 **Auth store** that persists bearer tokens and exposes login/logout helpers
- 🔁 **Axios client** that injects bearer tokens into every request and handles common HTTP failures
- 📦 **Modern tooling**: Svelte 5, SvelteKit 2, Tailwind CSS 4, DaisyUI 5, Prettier 3

## Prerequisites

- Node.js 20+
- npm 10+

## Getting started

```bash
cd crew-builder
npm install
npm run dev
```

The app runs on <http://localhost:5173> by default.

### Available scripts

| Command          | Description                                |
| ---------------- | ------------------------------------------ |
| `npm run dev`    | Start the Vite dev server                  |
| `npm run build`  | Create a production build                  |
| `npm run preview`| Preview the production build locally       |
| `npm run check`  | Run `svelte-check` for type and lint hints |

## Security hardening

Running `npm install` now triggers a post-install patch step that mitigates the
`cookie` (GHSA-pxg6-pf52-xh8x) and `esbuild` (GHSA-67mh-4wv8-2f99) advisories
without forcing breaking framework upgrades. The script:

- Replaces the transitive `cookie` implementation with a hardened parser and
  serializer that reject out-of-spec values.
- Disables the vulnerable `esbuild.serve()` helper that allowed cross-origin
  access to the development server.
- Marks both packages with `-patched` versions inside `package-lock.json` so
  future audits record that the fixes are applied locally.

If you reinstall dependencies in an environment where `postinstall` hooks are
disabled, run the patcher manually:

```bash
npm run postinstall
```

## Authentication helpers

The auth store (`src/lib/stores/auth.ts`) keeps the user profile and bearer token in local storage. It exposes:

- `init()` – restore session data at start-up
- `login(email, password)` – call the `/auth/login` API with the `x-auth-method: BasicAuth` header
- `logout()` – clear storage and redirect to `/login`
- `checkAuth()` – lightweight token presence check

Derived stores `isAuthenticated` and `currentUser` are exported for convenience.

## API client

An Axios instance lives in `src/lib/api/client.ts`. It automatically injects the bearer token and reacts to `401` responses by clearing storage and redirecting to `/login`. Feature-specific APIs are grouped under `src/lib/api`:

- `auth.login` – authentication endpoint
- `crew.*` – CRUD helpers for crew management

## Styling

Tailwind CSS v4 is enabled through the official Vite plugin. DaisyUI v5 powers ready-made components and the theme switcher. Theme selection is stored in local storage and updates the `data-theme` attribute on the document root.

## Export format

The `crewStore` still produces JSON compatible with the AgentCrew backend:

```json
{
  "name": "research_pipeline",
  "description": "Sequential pipeline for research and writing",
  "execution_mode": "sequential",
  "agents": [
    {
      "agent_id": "agent_1",
      "name": "Agent 1",
      "agent_class": "Agent",
      "config": {
        "model": "gemini-2.5-pro",
        "temperature": 0.7
      },
      "system_prompt": "You are an expert AI agent."
    }
  ]
}
```

Download the definition via the toolbar’s **Export JSON** button or push it directly to your backend with **Upload**.

## Next steps

- Wire the auth store into your login route
- Extend `crewStore` with persistence or backend syncing
- Add new DaisyUI themes to `themeOptions` in `ThemeToggle.svelte`
- Introduce additional execution modes once the backend supports them

Happy building! 🦜
