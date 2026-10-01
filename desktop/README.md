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
| `npm run lint` | Oxlint + Stylelint |
| `npm run build` | Build the renderer into `dist/` |
| `npm run build:electron` | Build and package with Electron Builder (does not bundle Python, Ollama or Tesseract) |

## Layout

| Path | Contents |
| --- | --- |
| `electron/main.cjs` | Starts local services, opens the window, whitelisted IPC handlers |
| `electron/preload.cjs` | The `window.localiAPI` bridge |
| `src/components/Chat/` | Chat screen and message bubbles |
| `src/hooks/` | `useChatStream` (streaming state), `useTheme` (light/dark) |
| `src/styles/tokens/` | Design tokens: primitives, semantic roles, spacing |

## Bridge

| Method | Backend call |
| --- | --- |
| `health()` | `GET /health` and Ollama `/api/tags` |
| `chat(message, conversationId)` | `POST /chat` |
| `chatStream.start(message, conversationId, useDocs)` | WebSocket `/chat/stream` |
| `search(query)` | `GET /search` |
| `ingest(fullReset)` | `POST /ingest` (runs in the background) |
| `ingestStatus()` | `GET /ingest/status` |
| `files.list(path)` | `GET /files` |
| `files.reveal(relativePath)` | Opens the file in Explorer; workspace paths only |
