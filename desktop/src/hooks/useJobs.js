// Hook that follows background jobs: loads the active ones, then applies the live job events the
// main process forwards from /jobs/events. A finished job stays visible for a few seconds.

import { useCallback, useEffect, useState } from 'react'

const FINISHED_VISIBLE_MS = 6000

const byCreation = (a, b) => a.created_at.localeCompare(b.created_at)

export function isActive(job) {
  return job.state === 'queued' || job.state === 'running'
}

// Replaces the list with the active jobs, e.g. after the events socket reconnects and may have missed events.
async function loadActiveJobs(setJobs) {
  try {
    const active = await window.localiAPI.jobs.listActive()
    setJobs(active.sort(byCreation))
  } catch {
    // The backend may still be starting; the sync sent when the events socket connects loads the list.
  }
}

export function useJobs() {
  const [jobs, setJobs] = useState([])

  const applyJob = useCallback((job) => {
    setJobs((previous) => [...previous.filter((existing) => existing.id !== job.id), job].sort(byCreation))
    if (!isActive(job)) {
      setTimeout(() => setJobs((previous) => previous.filter((existing) => existing.id !== job.id || isActive(existing))), FINISHED_VISIBLE_MS)
    }
  }, [])

  const cancel = useCallback(
    async (id) => {
      try {
        applyJob(await window.localiAPI.jobs.cancel(id))
      } catch {
        loadActiveJobs(setJobs) // it may already have finished
      }
    },
    [applyJob],
  )

  useEffect(() => {
    const api = window.localiAPI?.jobs
    if (!api) return undefined
    loadActiveJobs(setJobs)
    const unsubscribers = [api.onEvent(applyJob), api.onSync(() => loadActiveJobs(setJobs))]
    return () => unsubscribers.forEach((unsubscribe) => unsubscribe())
  }, [applyJob])

  return { jobs, cancel }
}
