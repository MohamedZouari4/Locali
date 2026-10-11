// Hook for the project dialog: loads one project with its folders and file count, saves its name and
// instructions, adds folders through the native picker (opened by the main process, so the page never
// sends a path), changes a folder's permission, removes one, and starts a file scan.
// When a scan of this project finishes (seen in `jobs`, from useJobs), the file count is reloaded.
// addFolder and scanFiles take an explicit project id, so the dialog can add a folder to a project it
// created a moment ago, before this hook has re-rendered with the new id.

import { useCallback, useEffect, useRef, useState } from 'react'

// Electron prefixes errors from the main process; keep only the backend's message.
function readable(error) {
  return String(error?.message ?? error).replace(/^Error invoking remote method '[^']+': (Error: )?/, '')
}

export function useProject(projectId, jobs) {
  const [project, setProject] = useState(null)
  const [message, setMessage] = useState(null) // { kind: 'error' | 'info' | 'success', text }
  const seenScans = useRef(new Set())

  const reload = useCallback(async (id) => {
    if (!id) return
    try {
      setProject(await window.localiAPI.projects.get(id))
    } catch (error) {
      setMessage({ kind: 'error', text: readable(error) })
    }
  }, [])

  // A slower answer for the previous project must not replace the current one.
  useEffect(() => {
    if (!projectId) return undefined
    let current = true
    window.localiAPI.projects.get(projectId).then(
      (loaded) => current && setProject(loaded),
      (error) => current && setMessage({ kind: 'error', text: readable(error) }),
    )
    return () => {
      current = false
    }
  }, [projectId])

  useEffect(() => {
    const finished = jobs.filter((job) => job.kind === 'catalog' && job.project === projectId && job.state === 'done')
    const fresh = finished.filter((job) => !seenScans.current.has(job.id))
    fresh.forEach((job) => seenScans.current.add(job.id))
    if (fresh.length > 0) reload(projectId)
  }, [jobs, projectId, reload])

  // Runs one change, then reloads the project `id`. Returns the change's result, true if it had none, or
  // false if it failed. `done` is the message shown when it worked: a string for a plain note,
  // { kind: 'success', text } for a confirmed change, null to clear it, or undefined to keep the current one.
  const run = useCallback(
    async (change, done, id) => {
      try {
        const result = await change()
        if (done !== undefined) setMessage(typeof done === 'string' ? { kind: 'info', text: done } : done)
        await reload(id)
        return result ?? true
      } catch (error) {
        setMessage({ kind: 'error', text: readable(error) })
        return false
      }
    },
    [reload],
  )

  const api = window.localiAPI?.projects

  const save = (name, instructions, ignorePatterns) => {
    const renamed = project && name !== project.name
    const rulesChanged = project && ignorePatterns.join('\n') !== project.ignore_patterns.join('\n')
    let text = renamed ? `Project renamed to “${name}”.` : 'Changes saved.'
    if (rulesChanged) text += ' Rescanning its files with the new ignore rules.'
    return run(() => api.update(projectId, name, instructions, ignorePatterns), { kind: 'success', text }, projectId)
  }

  const scanFiles = (id = projectId) => run(() => api.scanFiles(id), 'Scanning files. Follow it under Background tasks.', id)

  // A new folder is Read by default; scan right away so the file count reflects it. Returns whether a
  // folder was added (chooseFolder resolves to null when the picker is closed without choosing).
  const addFolder = async (id = projectId) => {
    const added = await run(() => api.chooseFolder(id, 'read'), undefined, id)
    if (!added || added === true) return false
    await scanFiles(id)
    return true
  }

  const setPermission = (folderId, permission) => run(() => api.setFolderPermission(projectId, folderId, permission), null, projectId)

  const removeFolder = async (folderId) => {
    if (await run(() => api.removeFolder(projectId, folderId), null, projectId)) await scanFiles()
  }

  // Until the switched-to project has loaded, show none rather than the previous one.
  const current = project?.id === projectId ? project : null

  return {
    project: current,
    message,
    save,
    addFolder,
    setPermission,
    removeFolder,
    scanFiles,
    notify: setMessage,
    clearMessage: () => setMessage(null),
  }
}
