// Electron main process: starts the Python API and Ollama if they aren't already running, opens the window,
// and forwards the renderer's IPC requests (streaming chat, conversations, background jobs, indexed folders, revealing files) to the local API.

const { app, BrowserWindow, dialog, ipcMain, shell } = require('electron');
const path = require('node:path');
const fs = require('node:fs');
const { spawn } = require('node:child_process');
const WebSocket = require('ws');
const { createApiClient } = require('./api/client.cjs');

const API_BASE_URL = 'http://127.0.0.1:8000'; // loopback only — ADR-015
const CHAT_STREAM_URL = 'ws://127.0.0.1:8000/chat/stream';
const CHAT_SUBPROTOCOL = 'locali.chat.v1'; // event contract version, see docs/CHAT_EVENTS.md
const JOB_EVENTS_URL = 'ws://127.0.0.1:8000/jobs/events';
const JOB_SUBPROTOCOL = 'locali.jobs.v1'; // see docs/JOB_EVENTS.md
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

// Polls until the service answers or the timeout passes. Returns whether it became ready.
async function waitForService(url, timeoutMs = 30_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (await isServiceReady(url)) return true;
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  return false;
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

  // Open the window only once both answer, or the renderer's first requests would be refused.
  const [apiReady, ollamaReady] = await Promise.all([
    backendProcess ? waitForService(`${API_BASE_URL}/health`) : true,
    ollamaProcess ? waitForService('http://127.0.0.1:11434/api/tags') : true,
  ]);
  if (!apiReady) console.error('[Locali] Local API did not become ready in time');
  if (!ollamaReady) console.error('[Locali] Ollama did not become ready in time');
}

function stopLocalServices() {
  backendProcess?.kill();
  ollamaProcess?.kill();
}

function createWindow() {
  const window = new BrowserWindow({
    // Windows draws the .ico sharper in the taskbar; packaged macOS builds take the icon from the app bundle.
    icon: path.join(__dirname, 'icons', process.platform === 'win32' ? 'icon.ico' : 'icon.png'),
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

// Without this, Windows groups the window under electron.exe in dev and shows Electron's icon.
if (process.platform === 'win32') app.setAppUserModelId('com.locali.desktop');

app.whenReady().then(async () => {
  await startLocalServices();
  createWindow();
  connectJobEvents();

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

const api = createApiClient(API_BASE_URL, getAuthToken);

// --- Whitelisted IPC channels. Each one wraps exactly one backend call. ---
// The backend's health checks. When the backend itself can't be reached, says so in the same shape.
ipcMain.handle('api:health', async () => {
  try {
    return await api.healthChecks();
  } catch {
    return {
      status: 'error',
      checks: [{
        id: 'service',
        status: 'error',
        title: 'Locali service not running',
        detail: `The app can't reach its local service at ${API_BASE_URL}.`,
        fix: 'Restart Locali. If you started the backend yourself, start it again.',
      }],
    };
  }
});

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

ipcMain.handle('api:conversations:list', () => api.listConversations());

ipcMain.handle('api:conversations:open', (_event, { id }) => api.openConversation(id));

ipcMain.handle('api:conversations:rename', (_event, { id, title }) => api.renameConversation(id, title));

ipcMain.handle('api:conversations:delete', (_event, { id }) => api.deleteConversation(id));

// One /jobs/events socket for the whole session; every job event goes to every window. It reconnects
// if the backend restarts, and tells the windows to reload the job list since events may have been missed.
let jobEventsSocket = null;
let jobEventsRetry = null;
let quitting = false;

function sendToWindows(channel, payload) {
  for (const window of BrowserWindow.getAllWindows()) window.webContents.send(channel, payload);
}

function connectJobEvents() {
  const token = getAuthToken();
  const ws = new WebSocket(JOB_EVENTS_URL, JOB_SUBPROTOCOL, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  jobEventsSocket = ws;

  ws.on('open', () => sendToWindows('api:jobs:sync'));
  ws.on('message', (raw) => {
    let payload;
    try {
      payload = JSON.parse(raw.toString());
    } catch {
      return;
    }
    if (payload.type === 'job') sendToWindows('api:jobs:event', payload.job); // ignore event types this client doesn't know
  });
  ws.on('error', () => {}); // 'close' follows and schedules the retry
  ws.on('close', () => {
    if (jobEventsSocket === ws) jobEventsSocket = null;
    if (!quitting) jobEventsRetry = setTimeout(connectJobEvents, 2000);
  });
}

function disconnectJobEvents() {
  quitting = true;
  clearTimeout(jobEventsRetry);
  jobEventsSocket?.close();
}

ipcMain.handle('api:jobs:list-active', () => api.listActiveJobs());

ipcMain.handle('api:jobs:cancel', (_event, { id }) => api.cancelJob(id));

ipcMain.handle('api:folders:list', () => api.listFolders());

// The folder comes from the native picker opened here, never from the page, so a compromised page
// can't add a path of its own choosing. The backend still checks it against the exclusions.
ipcMain.handle('api:folders:choose', async (event) => {
  const { canceled, filePaths } = await dialog.showOpenDialog(BrowserWindow.fromWebContents(event.sender), {
    title: 'Choose a folder to index',
    properties: ['openDirectory'],
  });
  if (canceled || filePaths.length === 0) return null;
  return api.addFolder(filePaths[0]);
});

ipcMain.handle('api:folders:remove', (_event, { id }) => api.removeFolder(id));

ipcMain.handle('api:indexing:start', () => api.startIndexing());

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

app.on('before-quit', () => {
  disconnectJobEvents();
  stopLocalServices();
});