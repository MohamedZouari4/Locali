import { useCallback, useEffect, useRef, useState } from 'react'

export function useChatStream() {
  const [messages, setMessages] = useState([])
  const conversationId = useRef(null)

  useEffect(() => {
    const chatStream = window.localiAPI?.chatStream
    if (!chatStream) return undefined

    const unsubChunk = chatStream.onChunk((chunk) => {
      setMessages((previous) => {
        const next = [...previous]
        const last = next[next.length - 1]
        if (last?.isStreaming) {
          next[next.length - 1] = { ...last, text: last.text + chunk }
        }
        return next
      })
    })

    const unsubFinal = chatStream.onFinal(
      ({ sources, conversationId: id }) => {
        conversationId.current = id ?? conversationId.current
        setMessages((previous) => {
          const next = [...previous]
          const last = next[next.length - 1]
          if (last?.isStreaming) {
            next[next.length - 1] = {
              ...last,
              isStreaming: false,
              sources: sources ?? [],
            }
          }
          return next
        })
      },
    )

    const unsubError = chatStream.onError((error) => {
      setMessages((previous) => {
        const next = [...previous]
        const last = next[next.length - 1]
        if (last?.isStreaming) {
          next[next.length - 1] = {
            ...last,
            isStreaming: false,
            text: last.text || `Unable to complete the response: ${error}`,
          }
        }
        return next
      })
    })

    return () => {
      unsubChunk()
      unsubFinal()
      unsubError()
    }
  }, [])

  const sendMessage = useCallback((text, useDocs = false) => {
    setMessages((previous) => [
      ...previous,
      { id: crypto.randomUUID(), role: 'user', text },
      {
        id: crypto.randomUUID(),
        role: 'assistant',
        text: '',
        isStreaming: true,
        sources: [],
      },
    ])
    if (!window.localiAPI?.chatStream) {
      setMessages((previous) => {
        const next = [...previous]
        const last = next[next.length - 1]
        if (last?.isStreaming) {
          next[next.length - 1] = {
            ...last,
            isStreaming: false,
            text: 'Open Locali through Electron to connect to the local assistant.',
          }
        }
        return next
      })
      return
    }

    window.localiAPI.chatStream.start(text, conversationId.current, useDocs)
  }, [])

  return { messages, sendMessage }
}
