// Main chat screen: sidebar with saved conversations and background tasks, message list, and composer with the "Use my docs" toggle.
// The sidebar footer opens the Indexed folders dialog. Features without backend support yet
// (attachments, settings, workspace stats, context panel) are hidden.

import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { useChatStream } from '../../hooks/useChatStream'
import { useConversations } from '../../hooks/useConversations'
import { useFolders } from '../../hooks/useFolders'
import { useHealth } from '../../hooks/useHealth'
import { useJobs } from '../../hooks/useJobs'
import { useTheme } from '../../hooks/useTheme'
import { BrandMark, Icon } from '../Icon'
import { ConversationList } from './ConversationList'
import { FoldersDialog } from './FoldersDialog'
import { HealthBanner } from './HealthBanner'
import { JobsPanel } from './JobsPanel'
import { MessageBubble } from './MessageBubble'
import './ChatScreen.css'

const suggestions = [
  { icon: 'file', title: 'Understand my files', text: 'Summarize the documents in my project folder.' },
  { icon: 'search', title: 'Find something', text: 'Find files related to my AI research.' },
  { icon: 'wrench', title: 'Fix a problem', text: 'Why is my Python application crashing?' },
  { icon: 'code', title: 'Understand my code', text: 'Explain how authentication works in this project.' },
]

// Below this width the sidebar floats over the chat instead of pushing it aside (matches ChatScreen.css).
const narrowScreen = '(max-width: 720px)'

export function ChatScreen() {
  const { messages, conversationId, sendMessage, retry, stop, loadConversation, newChat } = useChatStream()
  const { conversations, error: conversationsError, refresh, rename, remove } = useConversations()
  const { jobs, cancel: cancelJob } = useJobs()
  const { folders, message: folderMessage, addFolder, removeFolder, indexNow, clearMessage } = useFolders()
  const [foldersOpen, setFoldersOpen] = useState(false)
  const { theme, toggleTheme } = useTheme()
  const [draft, setDraft] = useState('')
  const [useDocs, setUseDocs] = useState(false)
  const [sidebarOpen, setSidebarOpen] = useState(() => !window.matchMedia(narrowScreen).matches)
  const { report: health, checkAgain } = useHealth()
  const scrollRef = useRef(null)
  const stickToBottom = useRef(true)
  const textareaRef = useRef(null)
  const isBusy = messages[messages.length - 1]?.isStreaming ?? false

  // The backend saves every turn, so reload the list on start and whenever an answer ends.
  useEffect(() => {
    if (!isBusy) refresh()
  }, [isBusy, refresh])

  // Follow the answer as it streams in, unless the user has scrolled up to read.
  useLayoutEffect(() => {
    const element = scrollRef.current
    if (element && stickToBottom.current && messages.length > 0) element.scrollTop = element.scrollHeight
  }, [messages])

  const handleScroll = (event) => {
    const { scrollTop, scrollHeight, clientHeight } = event.currentTarget
    stickToBottom.current = scrollHeight - scrollTop - clientHeight < 80
  }

  const closeSidebarOnNarrowScreen = () => {
    if (window.matchMedia(narrowScreen).matches) setSidebarOpen(false)
  }

  const startNewChat = () => {
    if (isBusy) stop()
    stickToBottom.current = true
    newChat()
    setDraft('')
    closeSidebarOnNarrowScreen()
    textareaRef.current?.focus()
  }

  const openConversation = (id) => {
    if (isBusy) stop()
    stickToBottom.current = true
    loadConversation(id).catch(refresh) // it may have been deleted elsewhere
    closeSidebarOnNarrowScreen()
  }

  const deleteConversation = async (conversation) => {
    if (!window.confirm(`Delete "${conversation.title || 'Untitled chat'}"? This can't be undone.`)) return
    if ((await remove(conversation.id)) && conversation.id === conversationId) startNewChat()
  }

  const activeTitle = conversationId ? conversations.find((conversation) => conversation.id === conversationId)?.title || 'Untitled chat' : 'New conversation'

  const handleSubmit = (event) => {
    event.preventDefault()
    const text = draft.trim()
    if (!text || isBusy) return
    stickToBottom.current = true
    sendMessage(text, useDocs)
    setDraft('')
  }

  // "Use my docs" needs something to read: with no folders yet, turning it on opens the folder dialog.
  const toggleDocs = () => {
    if (!useDocs && folders.length === 0) setFoldersOpen(true)
    setUseDocs(!useDocs)
  }

  const closeFolders = () => {
    setFoldersOpen(false)
    clearMessage()
  }

  const fillSuggestion = (text) => {
    setDraft(text)
    textareaRef.current?.focus()
  }

  // Dropped files are ignored until attachments exist; without this, Electron would open the file in the window.
  return (
    <div className={`app-shell ${sidebarOpen ? '' : 'app-shell--collapsed'}`} onDragOver={(event) => event.preventDefault()} onDrop={(event) => event.preventDefault()}>
      <aside className="sidebar" aria-label="Conversations" inert={!sidebarOpen}>
        <div className="sidebar__inner">
          <div className="sidebar__brand">
            <BrandMark />
            <div>
              <strong>Locali</strong>
              <small>Personal AI workspace</small>
            </div>
          </div>

          <button className="new-chat" type="button" onClick={startNewChat}>
            <Icon name="plus" /> New chat
          </button>

          <nav className="sidebar__list">
            <ConversationList conversations={conversations} activeId={conversationId} error={conversationsError} onOpen={openConversation} onRename={rename} onDelete={deleteConversation} />
          </nav>

          <JobsPanel jobs={jobs} onCancel={cancelJob} />

          <footer className="sidebar__footer">
            <span className={`status ${health?.status === 'ok' ? '' : 'status--offline'}`}>
              <i aria-hidden="true" /> {!health ? 'Checking…' : health.status === 'ok' ? 'Running locally' : 'Needs attention'}
            </span>
            <button className="icon-button sidebar__folders" type="button" onClick={() => setFoldersOpen(true)} aria-label="Indexed folders" title="Indexed folders">
              <Icon name="folder" />
            </button>
            <button className="icon-button" type="button" onClick={toggleTheme} aria-label={theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'} title={theme === 'dark' ? 'Light theme' : 'Dark theme'}>
              <Icon name={theme === 'dark' ? 'sun' : 'moon'} />
            </button>
          </footer>
        </div>
      </aside>
      {sidebarOpen && <button className="sidebar-scrim" type="button" aria-label="Close sidebar" onClick={() => setSidebarOpen(false)} />}

      <main className="chat-main">
        <header className="chat-header">
          <button className="icon-button" type="button" onClick={() => setSidebarOpen(!sidebarOpen)} aria-label={sidebarOpen ? 'Hide sidebar' : 'Show sidebar'} aria-expanded={sidebarOpen}>
            <Icon name="sidebar" size={18} />
          </button>
          <h1>{activeTitle}</h1>
          <span className="privacy-badge"><Icon name="lock" size={13} /> On-device</span>
        </header>

        <HealthBanner report={health} onCheckAgain={checkAgain} />

        <div className="chat-scroll" ref={scrollRef} onScroll={handleScroll} aria-live="polite">
          <div className="chat-thread">
            {messages.length === 0 ? (
              <div className="chat-empty">
                <div className="chat-empty__mark"><BrandMark size={48} /></div>
                <h2>What can we work on?</h2>
                <p>Ask about your files, projects, or code. Everything stays on this device.</p>
                <div className="suggestion-grid">
                  {suggestions.map((suggestion) => (
                    <button className="suggestion-card" type="button" key={suggestion.title} onClick={() => fillSuggestion(suggestion.text)}>
                      <span className="suggestion-card__icon"><Icon name={suggestion.icon} size={17} /></span>
                      <span className="suggestion-card__text">
                        <strong>{suggestion.title}</strong>
                        <small>{suggestion.text}</small>
                      </span>
                      <span className="suggestion-card__arrow"><Icon name="arrowUpRight" size={14} /></span>
                    </button>
                  ))}
                </div>
              </div>
            ) : (
              messages.map((message, index) => <MessageBubble key={message.id} message={message} onRetry={index === messages.length - 1 ? retry : undefined} />)
            )}
          </div>
        </div>

        <div className="composer-wrap">
          <form className="composer" onSubmit={handleSubmit}>
            <textarea
              ref={textareaRef}
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter' && !event.shiftKey) {
                  event.preventDefault()
                  handleSubmit(event)
                }
              }}
              placeholder="Ask Locali anything about your workspace…"
              aria-label="Message"
              disabled={isBusy}
              rows={1}
            />
            <div className="composer__footer">
              <button className={`docs-toggle ${useDocs ? 'docs-toggle--on' : ''}`} type="button" onClick={toggleDocs} aria-pressed={useDocs} title="Answer using the files in your workspace">
                <Icon name="file" size={15} /> Use my docs
              </button>
              <span className="composer__hint"><kbd>Shift</kbd> + <kbd>Enter</kbd> for a new line</span>
              {isBusy ? (
                <button className="send-button send-button--stop" type="button" onClick={stop} aria-label="Stop generating"><Icon name="stop" /></button>
              ) : (
                <button className="send-button" type="submit" disabled={!draft.trim()} aria-label="Send message"><Icon name="arrowUp" size={18} /></button>
              )}
            </div>
          </form>
          <p className="composer-note">Private · Processed on this device. Answers can be wrong, so check what matters.</p>
        </div>
      </main>

      <FoldersDialog open={foldersOpen} onClose={closeFolders} folders={folders} message={folderMessage} onAdd={addFolder} onRemove={removeFolder} onIndexNow={indexNow} />
    </div>
  )
}
