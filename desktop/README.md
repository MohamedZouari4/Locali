# Locali desktop

Electron + React client for Locali. The page talks only to the preload bridge (`window.localiAPI`);
the Electron main process makes every call to the local API on `127.0.0.1:8000` and holds the token.

## Run

```powershell
npm install
npm run dev          # Vite on :5173 + Electron
```

On start, Electron launches the backend with `backend/.venv` (run `uv sync` in `backend/` first)
and `ollama serve`, if they are not already running.

| Command | Purpose |
| --- | --- |
| `npm run dev` | Vite and Electron together |
| `npm run dev:vite` | Vite only |
| `npm run dev:electron` | Electron, once Vite is up |
| `npm run lint` | Oxlint + Stylelint (Stylelint forbids raw colors; use the tokens) |
| `npm run typecheck` | Type-checks the Electron API client against `schema.d.ts` |
| `npm run generate:api` | Regenerates `electron/api/schema.d.ts` from `openapi.json`; `dev` and `build` run it first |
| `npm run build` | Build the renderer into `dist/` |
| `npm run build:electron` | Build and package with Electron Builder (does not bundle Python, Ollama or Tesseract) |

After a backend route changes, run `uv run python -m scripts.export_openapi` in `backend/`, then
`npm run generate:api` here, and commit both `electron/api/openapi.json` and `schema.d.ts`.

## Layout

| Path | Contents |
| --- | --- |
| `electron/main.cjs` | Starts local services, opens the window, whitelisted IPC handlers, the chat and job WebSockets |
| `electron/preload.cjs` | The `window.localiAPI` bridge |
| `electron/api/` | `client.cjs`, the typed API client, and the generated `openapi.json` and `schema.d.ts` |
| `src/components/Chat/` | Chat screen, project switcher (custom menu) and Project dialog, conversation list, message bubbles, Indexed folders dialog, Background tasks panel, health banner |
| `src/components/Intro/` | Startup intro (animation, synthesized sound) |
| `src/hooks/` | `useChatStream` (streaming state), `useConversations` (sidebar list), `useCurrentProject` (project list and the current one, remembered on this device), `useProject` (the Project dialog), `useFolders`, `useJobs`, `useHealth`, `useServicesReady`, `useTheme` (light/dark) |
| `src/styles/tokens/` | Design tokens: primitives, semantic roles, spacing |

## Startup intro

The window opens at once and plays a ~6 s intro (`src/components/Intro/`) while Electron starts the
API and Ollama. Particles swirl in and form the logo, the name and tagline appear, and then the intro
fades into the chat screen. The chat screen mounts only after `servicesReady()` resolves. If the
intro ends before that, it shows "Starting local services…" until the services are ready, or until
45 s pass, when the health banner takes over.

| File | Contents |
| --- | --- |
| `timeline.js` | All cue times; the CSS gets them as `--t-*` properties, the canvas and sound read them directly |
| `logoParticles.js` | Canvas scene: dust and the particles that form the mark |
| `introAudio.js` | Web Audio synthesis: pad, whoosh, impact, chime and outro |
| `mark.js` | Logo geometry shared by the SVG and the particle sampler |
| `StartupIntro.jsx` / `.css` | Overlay, phases, exit |

- **No skipping:** there are no on-screen controls and no key ends it early; it always plays in full.
- **Sound:** always plays, since Electron allows autoplay. In a plain browser, autoplay may be blocked;
  the intro then plays silently.
- **Reduced motion:** shows the logo without moving it, plays only the chime, and lasts about 2 s.
- **Replays:** plays on every load, including a reload (`Ctrl+R`).

**Assets and licences:** the intro uses no third-party assets. The logo is the project's own icon
(`electron/icons/icon.svg`). The sound is generated in code at runtime, so the intro ships no audio
files. Both are covered by the repository's MIT licence.

## Bridge

| Method | Backend call |
| --- | --- |
| `servicesReady()` | None; resolves once the main process has started (or given up waiting for) the API and Ollama |
| `health()` | `GET /health/checks`; a "service not running" report if the API can't be reached |
| `projects.list()` / `projects.create(name, instructions)` | `GET /projects` / `POST /projects` |
| `projects.get(id)` / `projects.update(id, name, instructions)` / `projects.remove(id)` | `GET` / `PATCH` / `DELETE /projects/{id}` |
| `projects.chooseFolder(id, permission)` | Opens the native folder picker in the main process, then `POST /projects/{id}/folders`; the page never sends a path |
| `projects.setFolderPermission(id, folderId, permission)` / `projects.removeFolder(id, folderId)` | `PATCH` / `DELETE /projects/{id}/folders/{folderId}` |
| `projects.scanFiles(id)` | `POST /projects/{id}/catalog` (runs as a background job) |
| `conversations.list(projectId)` | `GET /conversations?project_id=...` |
| `conversations.open(id)` / `rename(id, title)` / `remove(id)` | `GET` / `PATCH` / `DELETE /conversations/{id}` |
| `chatStream.start(message, projectId, conversationId, useDocs)` | WebSocket `/chat/stream` (`locali.chat.v2`); answers arrive through `onChunk`, `onFinal`, `onError` and `onDone` |
| `chatStream.stop()` | Closes the socket; the backend keeps what arrived, marked incomplete |
| `jobs.listActive()` / `jobs.cancel(id)` | `GET /jobs?state=queued&state=running` / `POST /jobs/{id}/cancel` |
| `jobs.onEvent(callback)` / `jobs.onSync(callback)` | Events from WebSocket `/jobs/events`; `onSync` fires on (re)connect so the list can be reloaded |
| `folders.list()` / `folders.remove(id)` | `GET /folders` / `DELETE /folders/{id}` |
| `folders.choose()` | Opens the native folder picker in the main process, then `POST /folders`; the page never sends a path |
| `indexing.start()` | `POST /ingest` (runs as a background job) |
| `files.reveal(relativePath)` | None; opens the file in Explorer, workspace (`AI-Workspace/`) paths only |

See [docs/BRIDGE_AUDIT.md](../docs/BRIDGE_AUDIT.md) for how each method was checked.
