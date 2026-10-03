// Hook that holds the chat messages and streams assistant replies from the main process over IPC.
// A streaming answer always ends in one of three ways: done, error (with a retry), or stopped.
// If the socket closes without done or error, that counts as an error, so the chat never stays loading.

import { useCallback, useEffect, useRef, useState } from 'react'

function newAssistantMessage() {
  return { id: crypto.randomUUID(), role: 'assistant', text: '', isStreaming: true, sources: [], error: null, stopped: false }
}

function readableError(error) {
  const text = String(error ?? '')
  if (text.includes('ECONNREFUSED') && text.includes('8000')) {
    return 'The local Locali service is not running. Start the backend, then try again.'
  }
  if (text.includes('11434')) {
    return 'Ollama is not responding. Make sure it is running, then try again.'
  }
  return text ? `Something went wrong: ${text}` : 'Something went wrong.'
}

export function useChatStream() {
  const [messages, setMessages] = useState([])
  const conversationId = useRef(null)
  const lastRequest = useRef(null)

  // Applies changes to the last message, but only while it is still streaming.
  const updateStreaming = useCallback((changes) => {
    setMessages((previous) => {
      const last = previous[previous.length - 1]
      if (!last?.isStreaming) return previous
      const update = typeof changes === 'function' ? changes(last) : changes
      return [...previous.slice(0, -1), { ...last, ...update }]
    })
  }, [])

  useEffect(() => {
    const chatStream = window.localiAPI?.chatStream
    if (!chatStream) return undefined

    const unsubscribers = [
      chatStream.onChunk((chunk) => updateStreaming((last) => ({ text: last.text + chunk }))),
      chatStream.onFinal(({ sources, conversationId: id }) => {
        conversationId.current = id ?? conversationId.current
        updateStreaming({ isStreaming: false, sources: sources ?? [] })
      }),
      chatStream.onError((error) => updateStreaming({ isStreaming: false, error: readableError(error) })),
      // The socket closed without done or error, for example because the backend stopped.
      chatStream.onDone(() =>
        updateStreaming({ isStreaming: false, error: 'The connection closed before the answer finished.' }),
      ),
    ]
    return () => unsubscribers.forEach((unsubscribe) => unsubscribe())
  }, [updateStreaming])

  const startStream = useCallback(
    (text, useDocs) => {
      lastRequest.current = { text, useDocs }
      const chatStream = window.localiAPI?.chatStream
      if (!chatStream) {
        updateStreaming({ isStreaming: false, error: 'Open Locali through Electron to connect to the local assistant.' })
        return
      }
      chatStream
        .start(text, conversationId.current, useDocs)
        .catch((error) => updateStreaming({ isStreaming: false, error: readableError(error?.message) }))
    },
    [updateStreaming],
  )

  const sendMessage = useCallback(
    (text, useDocs = false) => {
      setMessages((previous) => [...previous, { id: crypto.randomUUID(), role: 'user', text }, newAssistantMessage()])
      startStream(text, useDocs)
    },
    [startStream],
  )

  // Replaces the failed last answer with a new attempt at the same question.
  const retry = useCallback(() => {
    if (!lastRequest.current) return
    setMessages((previous) => [...previous.slice(0, -1), newAssistantMessage()])
    startStream(lastRequest.current.text, lastRequest.current.useDocs)
  }, [startStream])

  // Keeps the text received so far and closes the stream; the server stops generating.
  const stop = useCallback(() => {
    updateStreaming({ isStreaming: false, stopped: true })
    window.localiAPI?.chatStream?.stop()
  }, [updateStreaming])

  return { messages, sendMessage, retry, stop }
}
