// Hook that tells whether the local services (API and Ollama) are up. The main process opens the window
// straight away and starts them in the background; the chat screen waits for this, since its first
// requests would be refused before. Stops waiting after 45 seconds: the health banner then says what's wrong.

import { useEffect, useState } from 'react'

const GIVE_UP_AFTER_MS = 45_000

export function useServicesReady() {
  // Outside Electron (e.g. Vite alone in a browser) there is nothing to wait for.
  const [ready, setReady] = useState(() => !window.localiAPI?.servicesReady)

  useEffect(() => {
    if (ready) return undefined
    let cancelled = false
    const markReady = () => {
      if (!cancelled) setReady(true)
    }
    window.localiAPI.servicesReady().then(markReady, markReady)
    const timer = setTimeout(markReady, GIVE_UP_AFTER_MS)
    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [ready])

  return ready
}
