// Preload script: exposes the `window.localiAPI` bridge that the React app uses to call the main process over IPC.

const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('localiAPI', {
  // Resolves once the main process has started (or given up waiting for) the local API and Ollama.
  servicesReady: () => ipcRenderer.invoke('app:services-ready'),

  health: () => ipcRenderer.invoke('api:health'),

  projects: {
    list: () => ipcRenderer.invoke('api:projects:list'),
    create: (name, instructions) => ipcRenderer.invoke('api:projects:create', { name, instructions }),
    get: (id) => ipcRenderer.invoke('api:projects:get', { id }),
    update: (id, name, instructions, ignorePatterns) =>
      ipcRenderer.invoke('api:projects:update', { id, name, instructions, ignorePatterns }),
    remove: (id) => ipcRenderer.invoke('api:projects:delete', { id }),
    // Opens the native folder picker in the main process; resolves to the added folder, or null if cancelled.
    chooseFolder: (id, permission) => ipcRenderer.invoke('api:projects:folders:choose', { id, permission }),
    setFolderPermission: (id, folderId, permission) =>
      ipcRenderer.invoke('api:projects:folders:permission', { id, folderId, permission }),
    removeFolder: (id, folderId) => ipcRenderer.invoke('api:projects:folders:remove', { id, folderId }),
    scanFiles: (id) => ipcRenderer.invoke('api:projects:scan', { id }),
  },

  conversations: {
    list: (projectId) => ipcRenderer.invoke('api:conversations:list', { projectId }),
    open: (id) => ipcRenderer.invoke('api:conversations:open', { id }),
    rename: (id, title) => ipcRenderer.invoke('api:conversations:rename', { id, title }),
    remove: (id) => ipcRenderer.invoke('api:conversations:delete', { id }),
  },

  jobs: {
    listActive: () => ipcRenderer.invoke('api:jobs:list-active'),
    cancel: (id) => ipcRenderer.invoke('api:jobs:cancel', { id }),
    onEvent: (callback) => {
      const listener = (_event, job) => callback(job);
      ipcRenderer.on('api:jobs:event', listener);
      return () => ipcRenderer.removeListener('api:jobs:event', listener);
    },
    // The events socket (re)connected: reload the job list, since events may have been missed.
    onSync: (callback) => {
      const listener = () => callback();
      ipcRenderer.on('api:jobs:sync', listener);
      return () => ipcRenderer.removeListener('api:jobs:sync', listener);
    },
  },

  folders: {
    list: () => ipcRenderer.invoke('api:folders:list'),
    // Opens the native folder picker in the main process; resolves to the added folder, or null if cancelled.
    choose: () => ipcRenderer.invoke('api:folders:choose'),
    remove: (id) => ipcRenderer.invoke('api:folders:remove', { id }),
  },

  indexing: {
    start: () => ipcRenderer.invoke('api:indexing:start'),
  },

  files: {
    reveal: (relativePath) =>
      ipcRenderer.invoke('api:files:reveal', { relativePath }),
  },

  chatStream: {
    start: (message, projectId, conversationId, useDocs) =>
      ipcRenderer.invoke('api:chat:stream:start', { message, projectId, conversationId, useDocs }),
    stop: () => ipcRenderer.invoke('api:chat:stream:stop'),
    onChunk: (callback) => {
      const listener = (_event, chunk) => callback(chunk);
      ipcRenderer.on('api:chat:stream:chunk', listener);
      return () => ipcRenderer.removeListener('api:chat:stream:chunk', listener);
    },
    onDone: (callback) => {
      const listener = () => callback();
      ipcRenderer.on('api:chat:stream:done', listener);
      return () => ipcRenderer.removeListener('api:chat:stream:done', listener);
    },
    onFinal: (callback) => {
      const listener = (_event, finalPayload) => callback(finalPayload);
      ipcRenderer.on('api:chat:stream:final', listener);
      return () => ipcRenderer.removeListener('api:chat:stream:final', listener);
    },
    onError: (callback) => {
      const listener = (_event, error) => callback(error);
      ipcRenderer.on('api:chat:stream:error', listener);
      return () => ipcRenderer.removeListener('api:chat:stream:error', listener);
    },
  },
});