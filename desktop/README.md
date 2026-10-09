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
| `src/components/Intro/` | Startup intro (animation, synthesized sound) |
| `src/hooks/` | `useChatStream` (streaming state), `useTheme` (light/dark) |
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
| `StartupIntro.jsx` / `.css` | Overlay, phases, skip, sound toggle, exit |

- **Skip:** Esc or the Skip button. Skip ends the intro, or jumps straight to the loading state.
- **Sound:** Electron allows autoplay. In a plain browser, autoplay may be blocked; the intro then plays
  silently and the "Sound off" button starts the sound in time with the animation. The choice is
  saved in `localStorage` (`locali-intro-muted`).
- **Reduced motion:** shows the logo without moving it, plays only the chime, and lasts about 2 s.
- **Replays:** plays on every load, including a reload (`Ctrl+R`).

**Assets and licences:** the intro uses no third-party assets. The logo is the project's own icon
(`electron/icons/icon.svg`). The sound is generated in code at runtime, so the intro ships no audio
files. Both are covered by the repository's MIT licence.

## Bridge

| Method | Backend call |
| --- | --- |
| `servicesReady()` | None; resolves once the main process has started the API and Ollama |
| `health()` | `GET /health` and Ollama `/api/tags` |
| `chat(message, conversationId)` | `POST /chat` |
| `chatStream.start(message, conversationId, useDocs)` | WebSocket `/chat/stream` |
| `search(query)` | `GET /search` |
| `ingest(fullReset)` | `POST /ingest` (runs in the background) |
| `ingestStatus()` | `GET /ingest/status` |
| `files.list(path)` | `GET /files` |
| `files.reveal(relativePath)` | Opens the file in Explorer; workspace paths only |
