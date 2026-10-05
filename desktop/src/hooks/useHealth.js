// Hook that runs the backend's health checks on start, every 15 seconds and on request, so a problem
// such as Ollama being stopped shows up in the banner without restarting the app.

import { useCallback, useEffect, useState } from 'react'

const CHECK_EVERY_MS = 15_000

async function loadReport(setReport) {
  try {
    setReport(await window.localiAPI.health())
  } catch {
    // The main process answers even when the backend is down, so this only happens if it's closing.
  }
}

export function useHealth() {
  const [report, setReport] = useState(null) // null until the first check finishes

  useEffect(() => {
    if (!window.localiAPI?.health) return undefined
    loadReport(setReport)
    const timer = setInterval(() => loadReport(setReport), CHECK_EVERY_MS)
    return () => clearInterval(timer)
  }, [])

  const checkAgain = useCallback(() => loadReport(setReport), [])

  return { report, checkAgain }
}
