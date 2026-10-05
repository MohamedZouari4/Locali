// "Indexed folders" dialog: the folders Locali reads for "Use my docs", with Add folder…, Remove and
// Index now. Uses the native <dialog> element, so Esc closes it and focus stays inside while open.

import { useEffect, useRef } from 'react'
import { Icon } from '../Icon'

export function FoldersDialog({ open, onClose, folders, message, onAdd, onRemove, onIndexNow }) {
  const dialogRef = useRef(null)

  useEffect(() => {
    const dialog = dialogRef.current
    if (open && !dialog.open) dialog.showModal()
    if (!open && dialog.open) dialog.close()
  }, [open])

  return (
    <dialog ref={dialogRef} className="folders-dialog" aria-labelledby="folders-dialog-title" onClose={onClose}>
      <header className="folders-dialog__header">
        <h2 id="folders-dialog-title">Indexed folders</h2>
        <button className="icon-button" type="button" onClick={onClose} aria-label="Close">
          <Icon name="close" />
        </button>
      </header>
      <p className="folders-dialog__intro">Locali reads the files in these folders to answer with “Use my docs”. Everything stays on this device.</p>

      {folders.length === 0 ? (
        <p className="folders-dialog__empty">No folders yet. Add one to start.</p>
      ) : (
        <ul className="folders-dialog__list">
          {folders.map((folder) => (
            <li key={folder.id}>
              <Icon name="folder" />
              <span className="folders-dialog__path" title={folder.path}>{folder.path}</span>
              <button className="small-icon small-icon--danger" type="button" onClick={() => onRemove(folder.id)} aria-label={`Remove ${folder.path}`} title="Remove">
                <Icon name="trash" size={14} />
              </button>
            </li>
          ))}
        </ul>
      )}

      {message && (
        <p className={`folders-dialog__message folders-dialog__message--${message.kind}`} role={message.kind === 'error' ? 'alert' : 'status'}>
          {message.text}
        </p>
      )}

      <footer className="folders-dialog__actions">
        <button className="folders-dialog__button" type="button" onClick={onIndexNow} disabled={folders.length === 0}>
          Index now
        </button>
        <button className="folders-dialog__button folders-dialog__button--primary" type="button" onClick={onAdd}>
          <Icon name="plus" /> Add folder…
        </button>
      </footer>
    </dialog>
  )
}
