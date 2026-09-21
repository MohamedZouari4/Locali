import { useEffect, useState } from 'react'
import { useChatStream } from '../../hooks/useChatStream'
import { useTheme } from '../../hooks/useTheme'
import { MessageBubble } from './MessageBubble'
import './ChatScreen.css'

const suggestions = [
  { icon: '◌', title: 'Understand my files', text: 'Summarize the documents in my project folder.' },
  { icon: '⌕', title: 'Find something', text: 'Find files related to my AI research.' },
  { icon: '⌁', title: 'Fix a problem', text: 'Why is my Python application crashing?' },
  { icon: '↗', title: 'Understand my code', text: 'Explain how authentication works in this project.' },
]

const conversations = [
  { group: 'Today', items: ['Analyze project structure', 'Fix Python environment error'] },
  { group: 'Yesterday', items: ['Find my PDF about RAG', 'Explain authentication code'] },
  { group: 'Previous 7 days', items: ['Organize Downloads'] },
]

export function ChatScreen() {
  const { messages, sendMessage } = useChatStream()
  const { theme, toggleTheme } = useTheme()
  const [draft, setDraft] = useState('')
  const [useDocs, setUseDocs] = useState(false)
  const [sidebarOpen, setSidebarOpen] = useState(true)
  const [contextOpen, setContextOpen] = useState(false)
  const [isDragging, setIsDragging] = useState(false)
  const [ollamaReady, setOllamaReady] = useState(false)
  const isBusy = messages[messages.length - 1]?.isStreaming ?? false

  useEffect(() => {
    let active = true

    const checkHealth = async () => {
      try {
        const health = await window.localiAPI?.health()
        if (active) setOllamaReady(health?.ollama === true)
      } catch {
        if (active) setOllamaReady(false)
      }
    }

    checkHealth()
    return () => {
      active = false
    }
  }, [])

  const handleSubmit = (event) => {
    event.preventDefault()
    const text = draft.trim()
    if (!text || isBusy) return
    sendMessage(text, useDocs)
    setDraft('')
  }

  const fillSuggestion = (text) => setDraft(text)

  return (
    <main className="chat-screen" onDragEnter={(event) => { event.preventDefault(); setIsDragging(true) }} onDragOver={(event) => event.preventDefault()} onDragLeave={(event) => { if (event.currentTarget === event.target) setIsDragging(false) }} onDrop={(event) => { event.preventDefault(); setIsDragging(false) }}>
      {isDragging && <div className="drop-overlay"><strong>Drop files to analyze</strong><span>PDF · DOCX · TXT · MD · CSV · Code · Images</span></div>}
      <header className="topbar">
        <div className="brand-lockup"><button className="icon-button menu-button" type="button" onClick={() => setSidebarOpen(!sidebarOpen)} aria-label="Toggle sidebar">☰</button><span className="brand-mark">l<span>•</span></span><div><strong>Locali</strong><small>Personal AI Workspace</small></div></div>
        <div className="topbar-status"><span className={`status-pill ${ollamaReady ? '' : 'status-pill--offline'}`}><i /> {ollamaReady ? 'Running locally' : 'Ollama unavailable'}</span><span className="model-label">qwen3:4b</span><span className="workspace-label">My Workspace</span><button className="icon-button" type="button" onClick={toggleTheme} aria-label="Toggle theme">{theme === 'dark' ? '☼' : '☾'}</button><button className="avatar-button" type="button" aria-label="Open application menu">LM</button></div>
      </header>
      <div className="workspace-layout">
        <aside className={`sidebar ${sidebarOpen ? '' : 'sidebar--closed'}`}>
          <button className="new-chat" type="button" onClick={() => setDraft('')}><span>+</span> New chat <kbd>Ctrl N</kbd></button>
          <div className="sidebar-section"><div className="section-label"><span>Recent conversations</span><button className="small-icon" type="button" aria-label="Search conversations">⌕</button></div>{conversations.map((section) => <div className="conversation-group" key={section.group}><span className="group-label">{section.group}</span>{section.items.map((item) => <button className="conversation-item" type="button" key={item}>{item}</button>)}</div>)}</div>
          <div className="sidebar-bottom"><div className="workspace-summary"><span className="workspace-icon">⌂</span><div><strong>My Workspace</strong><span>1,248 files indexed</span><span>12 folders · Local indexing</span></div></div><button className="sidebar-link" type="button"><span>□</span> Workspace</button><button className="sidebar-link" type="button"><span>⚙</span> Settings</button></div>
        </aside>
        <section className="chat-column">
          <div className="conversation-header"><div><span className="eyebrow">PRIVATE WORKSPACE</span><h1>Conversation</h1></div><button className="context-trigger" type="button" onClick={() => setContextOpen(!contextOpen)}><span className="context-dot" /> Workspace context <strong>1,248 files</strong>⌄</button></div>
          <div className="chat-messages" aria-live="polite">{messages.length === 0 ? <div className="chat-empty"><div className="empty-orbit"><span>l</span></div><h2>What can we work on?</h2><p>Ask about your files, projects, code, or workspace.<br />Everything stays on your device.</p><div className="suggestion-grid">{suggestions.map((suggestion) => <button className="suggestion-card" type="button" key={suggestion.title} onClick={() => fillSuggestion(suggestion.text)}><span className="suggestion-icon">{suggestion.icon}</span><span><strong>{suggestion.title}</strong><small>{suggestion.text}</small></span><b>↗</b></button>)}</div></div> : messages.map((message) => <MessageBubble key={message.id} message={message} />)}</div>
          <div className="composer-wrap"><div className="composer-context"><span className="context-dot" /> {useDocs ? 'Using workspace context' : 'Workspace context off'} <button type="button" onClick={() => setContextOpen(!contextOpen)}>1,248 indexed files</button></div><form className="chat-composer" onSubmit={handleSubmit}><textarea value={draft} onChange={(event) => setDraft(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); handleSubmit(event) } }} placeholder="Ask Locali anything about your workspace..." aria-label="Message" disabled={isBusy} rows={2} /><div className="composer-footer"><div className="composer-tools"><button type="button" aria-label="Attach files">＋</button><button type="button">Files</button><button className={useDocs ? 'docs-toggle docs-toggle--active' : 'docs-toggle'} type="button" onClick={() => setUseDocs(!useDocs)} aria-pressed={useDocs}>▣ Using docs</button></div><span className="composer-hint">Shift + Enter for new line</span><button className="send-button" type="submit" disabled={isBusy || !draft.trim()} aria-label="Send message">{isBusy ? '◌' : '↑'}</button></div></form><span className="privacy-note">Private · Processing on this device</span></div>
        </section>
        {contextOpen && <aside className="context-panel"><div className="panel-heading"><div><span className="eyebrow">CURRENT CONTEXT</span><h2>Workspace context</h2></div><button className="small-icon" type="button" onClick={() => setContextOpen(false)} aria-label="Close context panel">×</button></div><div className="context-count"><strong>3</strong><span>sources used in this conversation</span></div><div className="source-list"><button type="button"><span>✓</span> architecture.md <small>Project root</small></button><button type="button"><span>✓</span> project-plan.pdf <small>Documents</small></button><button type="button"><span>✓</span> src/orchestrator.py <small>Source code</small></button></div><div className="panel-task"><span className="eyebrow">CURRENT TASK</span><strong>Ready for your question</strong><span>Locali will search your workspace when context is useful.</span></div><div className="local-card"><span className="status-pill"><i /> Local processing</span><p>Your conversation and indexed workspace stay on this device.</p></div></aside>}
      </div>
    </main>
  )
}
