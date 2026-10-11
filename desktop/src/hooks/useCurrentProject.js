// Hook for the project the chat screen works in, and the list to switch between, create and delete.
// Every chat belongs to a project. On start it opens the project used last (remembered on this device),
// else the one named General, creating General if there are no projects yet.

import { useCallback, useEffect, useState } from 'react'

const GENERAL = 'General'
const STORAGE_KEY = 'locali-current-project'

function findGeneral(projects) {
  return projects.find((project) => project.name.toLowerCase() === GENERAL.toLowerCase())
}

// Remembering the project is a convenience, so storage that is blocked or full is ignored.
function remembered() {
  try {
    return localStorage.getItem(STORAGE_KEY)
  } catch {
    return null
  }
}

function remember(id) {
  try {
    localStorage.setItem(STORAGE_KEY, id)
  } catch {
    // ignored, see above
  }
}

export function useCurrentProject() {
  const [projects, setProjects] = useState([])
  const [projectId, setProjectId] = useState(null)
  const [error, setError] = useState(null)

  const selectProject = useCallback((id) => {
    setProjectId(id)
    remember(id)
  }, [])

  const refreshProjects = useCallback(async () => {
    const list = await window.localiAPI.projects.list()
    setProjects(list)
    return list
  }, [])

  useEffect(() => {
    const api = window.localiAPI?.projects
    if (!api) return undefined
    let cancelled = false

    const pick = async () => {
      let list = await api.list()
      let project = list.find((p) => p.id === remembered()) ?? findGeneral(list) ?? list[0]
      if (!project) {
        // A 409 means another window, or React running this effect twice, created it just now.
        await api.create(GENERAL).catch(() => {})
        list = await api.list()
        project = findGeneral(list)
      }
      if (!project) throw new Error('No project')
      return { list, id: project.id }
    }

    pick()
      .then(({ list, id }) => {
        if (cancelled) return
        setProjects(list)
        setProjectId(id)
      })
      .catch(() => !cancelled && setError('Could not open your project.'))
    return () => {
      cancelled = true
    }
  }, [])

  // Creates a project and switches to it. Throws with the backend's message, for example a taken name.
  const createProject = useCallback(
    async (name, instructions) => {
      const project = await window.localiAPI.projects.create(name, instructions)
      await refreshProjects()
      selectProject(project.id)
      return project
    },
    [refreshProjects, selectProject],
  )

  // Deletes a project and, if it was the current one, switches to General or else the first project left.
  // Returns the project switched to. Throws with the backend's message.
  const deleteProject = useCallback(
    async (id) => {
      await window.localiAPI.projects.remove(id)
      const list = await refreshProjects()
      if (id !== projectId) return list.find((project) => project.id === projectId)
      const next = findGeneral(list) ?? list[0]
      if (next) selectProject(next.id)
      return next
    },
    [projectId, refreshProjects, selectProject],
  )

  return { projects, projectId, selectProject, createProject, deleteProject, refreshProjects, error }
}
