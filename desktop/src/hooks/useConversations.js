// Hook that loads the saved conversations for the sidebar and renames or deletes them through the local API.

import { useCallback, useState } from 'react'

export function useConversations() {
  const [conversations, setConversations] = useState([])
  const [error, setError] = useState(null)

  const refresh = useCallback(async () => {
    const api = window.localiAPI?.conversations
    if (!api) return
    try {
      setConversations(await api.list())
      setError(null)
    } catch {
      setError('Could not load your conversations.')
    }
  }, [])

  const rename = useCallback(
    async (id, title) => {
      try {
        await window.localiAPI.conversations.rename(id, title)
      } catch {
        setError('Could not rename the conversation.')
      }
      await refresh()
    },
    [refresh],
  )

  // Returns whether the conversation was deleted.
  const remove = useCallback(async (id) => {
    try {
      await window.localiAPI.conversations.remove(id)
      setConversations((previous) => previous.filter((conversation) => conversation.id !== id))
      return true
    } catch {
      setError('Could not delete the conversation.')
      return false
    }
  }, [])

  return { conversations, error, refresh, rename, remove }
}
