// Hook that picks the project the chat screen works in. Every chat belongs to a project; until the app
// has a project picker, that is the project named General, created on first use.

import { useEffect, useState } from 'react'

const GENERAL = 'General'

function findGeneral(projects) {
  return projects.find((project) => project.name.toLowerCase() === GENERAL.toLowerCase())
}

export function useCurrentProject() {
  const [projectId, setProjectId] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    const api = window.localiAPI?.projects
    if (!api) return undefined
    let cancelled = false

    const pick = async () => {
      let project = findGeneral(await api.list())
      // A 409 means another window, or React running this effect twice, created it just now.
      if (!project) project = await api.create(GENERAL).catch(async () => findGeneral(await api.list()))
      if (!project) throw new Error('No General project')
      return project.id
    }

    pick()
      .then((id) => !cancelled && setProjectId(id))
      .catch(() => !cancelled && setError('Could not open your project.'))
    return () => {
      cancelled = true
    }
  }, [])

  return { projectId, error }
}
