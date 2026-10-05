// Hook for the indexed folders: lists them, adds one through the native folder picker (opened by
// the main process, so the page never sends a path), removes one, and starts indexing.
// Adding a folder starts indexing straight away; progress shows in the Background tasks panel.

import { useCallback, useEffect, useState } from 'react'

// Electron prefixes errors from the main process; keep only the backend's message.
function readable(error) {
  return String(error?.message ?? error).replace(/^Error invoking remote method '[^']+': (Error: )?/, '')
}

export function useFolders() {
  const [folders, setFolders] = useState([])
  const [message, setMessage] = useState(null) // { kind: 'error' | 'info', text }

  const refresh = useCallback(async () => {
    const api = window.localiAPI?.folders
    if (!api) return
    try {
      setFolders(await api.list())
    } catch (error) {
      setMessage({ kind: 'error', text: readable(error) })
    }
  }, [])

  useEffect(() => {
    const api = window.localiAPI?.folders
    if (!api) return
    api.list().then(setFolders, (error) => setMessage({ kind: 'error', text: readable(error) }))
  }, [])

  const indexNow = useCallback(async () => {
    try {
      await window.localiAPI.indexing.start()
      setMessage({ kind: 'info', text: 'Indexing started. Follow it under Background tasks.' })
    } catch (error) {
      setMessage({ kind: 'error', text: readable(error) })
    }
  }, [])

  const addFolder = useCallback(async () => {
    try {
      const added = await window.localiAPI.folders.choose()
      if (!added) return // the picker was closed without choosing
      setMessage(null)
      await refresh()
      await indexNow()
    } catch (error) {
      setMessage({ kind: 'error', text: readable(error) })
    }
  }, [refresh, indexNow])

  const removeFolder = useCallback(
    async (id) => {
      try {
        await window.localiAPI.folders.remove(id)
        setMessage({ kind: 'info', text: 'Folder removed. Its files are being removed from the index.' })
        await refresh()
      } catch (error) {
        setMessage({ kind: 'error', text: readable(error) })
      }
    },
    [refresh],
  )

  return { folders, message, addFolder, removeFolder, indexNow, clearMessage: () => setMessage(null) }
}
