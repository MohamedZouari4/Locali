// Electron main process: starts the Python API and Ollama if they aren't already running, opens the window,
// and forwards the renderer's IPC requests (chat, streaming chat, search, ingest, files) to the local API.

const { app, BrowserWindow, ipcMain, shell } = require('electron');
const path = require('node:path');
const fs = require('node:fs');
const { spawn } = require('node:child_process');
const WebSocket = require('ws');

const API_BASE_URL = 'http://127.0.0.1:8000'; // loopback only — ADR-015
const CHAT_STREAM_URL = 'ws://127.0.0.1:8000/chat/stream';
const CHAT_SUBPROTOCOL = 'locali.chat.v1'; // event contract version, see docs/CHAT_EVENTS.md
const TOKEN_PATH = path.join(app.getPath('userData'), 'api-token');
const DEV_SERVER_URL = process.env.VITE_DEV_SERVER_URL;
const PROJECT_ROOT = path.join(__dirname, '..', '..');
const BACKEND_ROOT = path.join(PROJECT_ROOT, 'backend');
// The venv `uv sync` creates next to backend/pyproject.toml.
const PYTHON_EXECUTABLE = process.platform === 'win32'
  ? path.join(BACKEND_ROOT, '.venv', 'Scripts', 'python.exe')
  : path.join(BACKEND_ROOT, '.venv', 'bin', 'python');
// Must match PathSettings.allowed_root in backend/app/core/config.py.
// TODO: replace with the value from Settings (P3-E2-T3) once available.
const ALLOWED_ROOT = path.join(PROJECT_ROOT, 'AI-Workspace');

let backendProcess;
let ollamaProcess;

async function isServiceReady(url) {
  try {
    const response = await fetch(url);
    return response.ok;
  } catch {
    return false;
  }
}

function startProcess(command, args, options) {
  const child = spawn(command, args, { ...options, stdio: 'inherit', windowsHide: true });
  child.on('error', (error) => console.error(`[Locali] Could not start ${command}: ${error.message}`));
  return child;
}

async function startLocalServices() {
  if (!await isServiceReady(`${API_BASE_URL}/health`)) {
    if (fs.existsSync(PYTHON_EXECUTABLE) && fs.existsSync(path.join(BACKEND_ROOT, 'app', 'api', 'main.py'))) {
      console.log('[Locali] Starting local API');
      backendProcess = startProcess(PYTHON_EXECUTABLE, ['-m', 'uvicorn', 'app.api.main:app', '--host', '127.0.0.1', '--port', '8000'], { cwd: BACKEND_ROOT });
    } else {
      console.error('[Locali] Backend files or project Python environment were not found');
    }
  } else {
    console.log('[Locali] Local API already running');
  }

  if (!await isServiceReady('http://127.0.0.1:11434/api/tags')) {
    console.log('[Locali] Starting Ollama');
    ollamaProcess = startProcess('ollama', ['serve'], { cwd: PROJECT_ROOT });
  } else {
    console.log('[Locali] Ollama already running');
  }
}

function stopLocalServices() {
  backendProcess?.kill();
  ollamaProcess?.kill();
}

function createWindow() {
  const window = new BrowserWindow({
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      preload: path.join(__dirname, 'preload.cjs'),
    },
  });

  if (DEV_SERVER_URL) {
    window.loadURL(DEV_SERVER_URL);
    window.webContents.openDevTools({ mode: 'detach' });
  } else {
    window.loadFile(path.join(__dirname, '..', 'dist', 'index.html'));
  }
}

app.whenReady().then(async () => {
  await startLocalServices();
  createWindow();

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit();
  }
});

function getAuthToken() {
  // Written locally by the backend on startup (P2-E1-T3). Never committed,
  // never hardcoded, never sent to the renderer.
  const tokenPaths = [TOKEN_PATH, path.join(__dirname, '..', '..', '.auth_token')];
  for (const tokenPath of tokenPaths) {
    try {
      return fs.readFileSync(tokenPath, 'utf-8').trim();
    } catch {
    }
  }
  return null;
}

async function apiFetch(pathname, options = {}) {
  const token = getAuthToken();
  const res = await fetch(`${API_BASE_URL}${pathname}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...options.headers,
    },
  });
  if (!res.ok) {
    throw new Error(`API ${pathname} failed: ${res.status}`);
  }
  return res.json();
}

// --- Whitelisted IPC channels. Each one wraps exactly one backend call. ---
ipcMain.handle('api:health', async () => ({
  api: await isServiceReady(`${API_BASE_URL}/health`),
  ollama: await isServiceReady('http://127.0.0.1:11434/api/tags'),
}));

ipcMain.handle('api:chat', (_event, { message, conversationId }) =>
  apiFetch('/chat', {
    method: 'POST',
    body: JSON.stringify({ message, conversation_id: conversationId }),
  })
);

// Only one chat stream runs at a time. Events from any other socket (one the user stopped or
// replaced) are dropped, so they can't leak into the current answer.
let activeChatSocket = null;

function closeActiveChatSocket() {
  const ws = activeChatSocket;
  activeChatSocket = null;
  ws?.close();
}

ipcMain.handle(
  'api:chat:stream:start',
  (event, { message, conversationId, useDocs }) => {
    const token = getAuthToken();
    console.log(`[Locali] Starting chat stream${conversationId ? ` for ${conversationId}` : ''}`);
    closeActiveChatSocket();
    const ws = new WebSocket(CHAT_STREAM_URL, CHAT_SUBPROTOCOL, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    activeChatSocket = ws;
    const forward = (channel, payload) => {
      if (activeChatSocket === ws && !event.sender.isDestroyed()) event.sender.send(channel, payload);
    };

    ws.on('open', () => {
      console.log('[Locali] Chat stream connected');
      ws.send(JSON.stringify({ message, conversation_id: conversationId, use_docs: useDocs }));
    });
    let sources = [];
    ws.on('message', (raw) => {
      let payload;
      try {
        payload = JSON.parse(raw.toString());
      } catch {
        console.error('[Locali] Chat stream sent invalid JSON');
        return;
      }

      // Event contract: docs/CHAT_EVENTS.md. Ignore event types this client doesn't handle yet.
      switch (payload.type) {
        case 'token':
          forward('api:chat:stream:chunk', payload.text ?? '');
          break;
        case 'sources':
          sources = payload.sources ?? [];
          break;
        case 'done':
          console.log('[Locali] Chat stream completed');
          forward('api:chat:stream:final', {
            sources,
            conversationId: payload.conversation_id,
          });
          break;
        case 'error':
          console.error(`[Locali] Chat stream backend error: ${payload.text ?? 'unknown error'}`);
          forward('api:chat:stream:error', payload.text ?? 'The local API failed');
          break;
        default:
          break;
      }
    });
    ws.on('close', () => {
      console.log('[Locali] Chat stream closed');
      forward('api:chat:stream:done'); // the renderer treats a close without done/error as a failure
      if (activeChatSocket === ws) activeChatSocket = null;
    });
    ws.on('error', (error) => {
      console.error(`[Locali] Chat stream error: ${error.message}`);
      forward('api:chat:stream:error', error.message);
    });
  }
);

ipcMain.handle('api:chat:stream:stop', () => {
  console.log('[Locali] Chat stream stopped by user');
  closeActiveChatSocket();
});

ipcMain.handle('api:search', (_event, { query }) =>
  apiFetch(`/search?q=${encodeURIComponent(query)}`)
);

// Starts a background run; poll api:ingest:status for progress. Folders come from scan_drives in the backend config.
ipcMain.handle('api:ingest', (_event, { fullReset }) =>
  apiFetch(`/ingest?full_reset=${fullReset ? 'true' : 'false'}`, { method: 'POST' })
);

ipcMain.handle('api:ingest:status', () => apiFetch('/ingest/status'));

ipcMain.handle('api:files:list', (_event, { path: targetPath }) =>
  apiFetch(`/files?path=${encodeURIComponent(targetPath || '.')}`)
);

ipcMain.handle('api:files:reveal', (_event, { relativePath }) => {
  if (typeof relativePath !== 'string') {
    throw new Error('Refused: reveal path must be relative to the workspace root');
  }

  const root = path.resolve(ALLOWED_ROOT);
  const resolved = path.isAbsolute(relativePath)
    ? path.resolve(relativePath)
    : path.resolve(root, relativePath);
  const relative = path.relative(root, resolved);
  if (!relative || relative === '..' || relative.startsWith(`..${path.sep}`) || path.isAbsolute(relative)) {
    throw new Error('Refused: path escapes the allowed workspace root');
  }

  shell.showItemInFolder(resolved);
});

app.on('before-quit', stopLocalServices);