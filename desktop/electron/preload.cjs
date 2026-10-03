// Preload script: exposes the `window.localiAPI` bridge that the React app uses to call the main process over IPC.

const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('localiAPI', {
  health: () => ipcRenderer.invoke('api:health'),

  chat: (message, conversationId) =>
    ipcRenderer.invoke('api:chat', { message, conversationId }),

  search: (query) => ipcRenderer.invoke('api:search', { query }),

  ingest: (fullReset = false) => ipcRenderer.invoke('api:ingest', { fullReset }),

  ingestStatus: () => ipcRenderer.invoke('api:ingest:status'),

  files: {
    list: (path) => ipcRenderer.invoke('api:files:list', { path }),
    reveal: (relativePath) =>
      ipcRenderer.invoke('api:files:reveal', { relativePath }),
  },

  chatStream: {
    start: (message, conversationId, useDocs) =>
      ipcRenderer.invoke('api:chat:stream:start', { message, conversationId, useDocs }),
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