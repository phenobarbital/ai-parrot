# AgentUI

AgentUI is a SvelteKit 5 experience for authenticating with your AI Parrot instance and chatting with any available bot/agent.
It shares the same user-password authentication flow used in `crew-builder` and relies on the REST API endpoints already
available in the backend.

## Highlights

- 🔐 **Authentication-ready** – username/password login backed by the `/api/v1/login` endpoint and bearer token storage
- 🤖 **Agent directory** – pulls `/api/v1/bots` and renders the agents as interactive cards inspired by the provided mockup
- 💬 **Chat workspace** – full-screen chat window with bubble replies, lateral navigation rail, and a context panel, powered by
  `POST /api/v1/agents/chat/{agent_id}`
- 🎨 **DaisyUI + Tailwind v4** – same theming stack as `crew-builder`, including the global theme switcher component

## Getting started

```bash
cd agentui
npm install
npm run dev
```

Open <http://localhost:5173> and log in with the same credentials you use for the rest of the platform.

## Project layout

- `src/routes/login` – sign-in screen with toast-based feedback
- `src/routes/+page.svelte` – home dashboard that fetches `/api/v1/bots` and renders the agent grid
- `src/routes/talk/[agentId]` – agent-specific chat experience that posts new prompts to `/api/v1/agents/chat/{agent_id}`
- `src/lib/api` – typed wrappers around the REST endpoints (`bots` and `chat`)
- `src/lib/stores` – authentication, toast, and theme stores shared with the UI

## Scripts

| Command         | Description                              |
| --------------- | ---------------------------------------- |
| `npm run dev`   | Start the Vite dev server                |
| `npm run build` | Create a production build                |
| `npm run preview` | Preview the production build locally   |
| `npm run check` | Run `svelte-check` for diagnostics       |

Happy chatting! 🦜
