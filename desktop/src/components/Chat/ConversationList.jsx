// Sidebar list of saved conversations, grouped by when they were last active. Each one can be
// opened, renamed in place (double-click or the pencil) and deleted.

import { useMemo, useRef, useState } from 'react'
import { Icon } from '../Icon'

// SQLite stores UTC times as "YYYY-MM-DD HH:MM:SS".
function parseUtc(timestamp) {
  return new Date(`${timestamp.replace(' ', 'T')}Z`)
}

function groupLabel(date, now) {
  const startOfDay = (day) => new Date(day.getFullYear(), day.getMonth(), day.getDate())
  const days = Math.round((startOfDay(now) - startOfDay(date)) / 86_400_000)
  if (days <= 0) return 'Today'
  if (days === 1) return 'Yesterday'
  if (days < 7) return 'Previous 7 days'
  if (days < 30) return 'Previous 30 days'
  return 'Older'
}

// The API returns the most recently active first, so each group is a run of neighbours.
function groupConversations(conversations) {
  const now = new Date()
  const groups = []
  for (const conversation of conversations) {
    const label = groupLabel(parseUtc(conversation.updated_at), now)
    if (groups.at(-1)?.label !== label) groups.push({ label, items: [] })
    groups.at(-1).items.push(conversation)
  }
  return groups
}

function ConversationItem({ conversation, active, onOpen, onRename, onDelete }) {
  const [editing, setEditing] = useState(false)
  const [title, setTitle] = useState('')
  const cancelled = useRef(false)
  const label = conversation.title || 'Untitled chat'

  const startEditing = () => {
    setTitle(label)
    setEditing(true)
  }

  const finishEditing = () => {
    setEditing(false)
    if (cancelled.current) {
      cancelled.current = false
      return
    }
    const next = title.trim()
    if (next && next !== conversation.title) onRename(conversation.id, next)
  }

  if (editing) {
    return (
      <input
        className="conversation-rename"
        value={title}
        maxLength={200}
        autoFocus
        aria-label="Conversation title"
        onChange={(event) => setTitle(event.target.value)}
        onBlur={finishEditing}
        onKeyDown={(event) => {
          if (event.key === 'Escape') cancelled.current = true
          if (event.key === 'Enter' || event.key === 'Escape') event.currentTarget.blur()
        }}
      />
    )
  }

  return (
    <div className={`conversation-row ${active ? 'conversation-row--active' : ''}`}>
      <button
        className="conversation-item"
        type="button"
        title={label}
        aria-current={active ? 'true' : undefined}
        onClick={() => onOpen(conversation.id)}
        onDoubleClick={startEditing}
      >
        {label}
      </button>
      <div className="conversation-actions">
        <button className="small-icon" type="button" onClick={startEditing} aria-label={`Rename ${label}`} title="Rename"><Icon name="pencil" size={14} /></button>
        <button className="small-icon small-icon--danger" type="button" onClick={() => onDelete(conversation)} aria-label={`Delete ${label}`} title="Delete"><Icon name="trash" size={14} /></button>
      </div>
    </div>
  )
}

export function ConversationList({ conversations, activeId, error, onOpen, onRename, onDelete }) {
  const groups = useMemo(() => groupConversations(conversations), [conversations])

  if (error) return <p className="conversation-empty">{error}</p>
  if (conversations.length === 0) return <p className="conversation-empty">Your chats will appear here.</p>

  return groups.map((group) => (
    <div className="conversation-group" key={group.label}>
      <span className="group-label">{group.label}</span>
      {group.items.map((conversation) => (
        <ConversationItem
          key={conversation.id}
          conversation={conversation}
          active={conversation.id === activeId}
          onOpen={onOpen}
          onRename={onRename}
          onDelete={onDelete}
        />
      ))}
    </div>
  ))
}
