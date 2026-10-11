// Hook for the project settings dialog: loads one project with its folders and file count, saves its
// name and instructions, adds folders through the native picker (opened by the main process, so the page
// never sends a path), changes a folder's permission, removes one, and starts a file scan.
// When a scan of this project finishes (seen in `jobs`, from useJobs), the file count is reloaded.

import { useCallback, useEffect, useRef, useState } from 'react'

// Electron prefixes errors from the main process; keep only the backend's message.
function readable(error) {
  return String(error?.message ?? error).replace(/^Error invoking remote method '[^']+': (Error: )?/, '')
}

export function useProject(projectId, jobs) {
  const [project, setProject] = useState(null)
  const [message, setMessage] = useState(null) // { kind: 'error' | 'info', text }
  const seenScans = useRef(new Set())

  const reload = useCallback(async () => {
    if (!projectId) return
    try {
      setProject(await window.localiAPI.projects.get(projectId))
    } catch (error) {
      setMessage({ kind: 'error', text: readable(error) })
    }
  }, [projectId])

  useEffect(() => {
    if (!projectId) return
    window.localiAPI.projects.get(projectId).then(setProject, (error) => setMessage({ kind: 'error', text: readable(error) }))
  }, [projectId])

  useEffect(() => {
    const finished = jobs.filter((job) => job.kind === 'catalog' && job.project === projectId && job.state === 'done')
    const fresh = finished.filter((job) => !seenScans.current.has(job.id))
    fresh.forEach((job) => seenScans.current.add(job.id))
    if (fresh.length > 0) reload()
  }, [jobs, projectId, reload])

  // Runs one change, then reloads the project. Returns whether the change worked.
  const run = useCallback(
    async (change, info) => {
      try {
        const result = await change()
        setMessage(info ? { kind: 'info', text: info } : null)
        await reload()
        return result ?? true
      } catch (error) {
        setMessage({ kind: 'error', text: readable(error) })
        return false
      }
    },
    [reload],
  )

  const api = window.localiAPI?.projects

  const save = (name, instructions) => run(() => api.update(projectId, name, instructions), 'Saved.')

  // A new folder is Read by default; scan right away so the file count reflects it.
  const addFolder = async () => {
    const added = await run(() => api.chooseFolder(projectId, 'read'))
    if (added && added !== true) await scanFiles()
  }

  const setPermission = (folderId, permission) => run(() => api.setFolderPermission(projectId, folderId, permission))

  const removeFolder = async (folderId) => {
    if (await run(() => api.removeFolder(projectId, folderId))) await scanFiles()
  }

  const scanFiles = () => run(() => api.scanFiles(projectId), 'Scanning files. Follow it under Background tasks.')

  // Until the switched-to project has loaded, show none rather than the previous one.
  const current = project?.id === projectId ? project : null

  return { project: current, message, save, addFolder, setPermission, removeFolder, scanFiles, clearMessage: () => setMessage(null) }
}
