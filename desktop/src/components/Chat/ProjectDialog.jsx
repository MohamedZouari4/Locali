// Project dialog. In create mode it asks for a name and instructions; once created, the chat screen
// switches to the new project and the dialog stays open on it. In edit mode it also lists the project's
// folders with their Read/Act permission, Add folder… and Remove, and how many files the catalog holds,
// with Scan files. Uses the native <dialog> element, like the Indexed folders dialog.

import { useEffect, useRef, useState } from 'react'
import { Icon } from '../Icon'

const permissions = [
  { value: 'read', label: 'Read', hint: 'Locali may search this folder.' },
  { value: 'act', label: 'Act', hint: 'Locali may also change files in this folder.' },
]

export function ProjectDialog({ open, mode, project, message, onClose, onCreate, onSave, onAddFolder, onSetPermission, onRemoveFolder, onScanFiles }) {
  const creating = mode === 'create'
  const dialogRef = useRef(null)
  // The chat screen gives the dialog a key per mode and project, so the form starts fresh for each.
  const [name, setName] = useState(() => (creating ? '' : (project?.name ?? '')))
  const [instructions, setInstructions] = useState(() => (creating ? '' : (project?.instructions ?? '')))
  const [createError, setCreateError] = useState(null)

  useEffect(() => {
    const dialog = dialogRef.current
    if (open && !dialog.open) dialog.showModal()
    if (!open && dialog.open) dialog.close()
  }, [open])

  const submit = async (event) => {
    event.preventDefault()
    if (!name.trim()) return
    if (!creating) {
      onSave(name.trim(), instructions)
      return
    }
    try {
      await onCreate(name.trim(), instructions)
    } catch (error) {
      setCreateError(String(error?.message ?? error).replace(/^Error invoking remote method '[^']+': (Error: )?/, ''))
    }
  }

  const unchanged = !creating && project && name.trim() === project.name && instructions === project.instructions
  const shownMessage = creating ? (createError ? { kind: 'error', text: createError } : null) : message

  return (
    <dialog ref={dialogRef} className="folders-dialog project-dialog" aria-labelledby="project-dialog-title" onClose={onClose}>
      <header className="folders-dialog__header">
        <h2 id="project-dialog-title">{creating ? 'New project' : 'Project settings'}</h2>
        <button className="icon-button" type="button" onClick={onClose} aria-label="Close">
          <Icon name="close" />
        </button>
      </header>
      <p className="folders-dialog__intro">
        {creating
          ? 'A project keeps its own chats, folders and instructions. Everything stays on this device.'
          : 'This project keeps its own chats. Its folders and instructions are saved here; answers don’t use them yet.'}
      </p>

      <form className="project-dialog__form" onSubmit={submit}>
        <label className="project-dialog__field">
          <span>Name</span>
          <input value={name} onChange={(event) => setName(event.target.value)} maxLength={100} required autoFocus />
        </label>
        <label className="project-dialog__field">
          <span>Instructions</span>
          <textarea
            value={instructions}
            onChange={(event) => setInstructions(event.target.value)}
            maxLength={20000}
            rows={3}
            placeholder="For example: answer in French, and cite the file names."
          />
        </label>
        <div className="folders-dialog__actions">
          <button className="folders-dialog__button folders-dialog__button--primary" type="submit" disabled={!name.trim() || unchanged}>
            {creating ? 'Create project' : 'Save'}
          </button>
        </div>
      </form>

      {!creating && project && (
        <>
          <h3 className="project-dialog__section">Folders</h3>
          {project.folders.length === 0 ? (
            <p className="folders-dialog__empty">No folders yet. Add one so Locali can find this project&apos;s files.</p>
          ) : (
            <ul className="folders-dialog__list">
              {project.folders.map((folder) => (
                <li key={folder.id}>
                  <Icon name="folder" />
                  <span className="folders-dialog__path" title={folder.path}>{folder.path}</span>
                  <select
                    className="project-dialog__permission"
                    value={folder.permission}
                    onChange={(event) => onSetPermission(folder.id, event.target.value)}
                    aria-label={`Permission for ${folder.path}`}
                    title={permissions.find((p) => p.value === folder.permission)?.hint}
                  >
                    {permissions.map((permission) => (
                      <option key={permission.value} value={permission.value}>{permission.label}</option>
                    ))}
                  </select>
                  <button className="small-icon small-icon--danger" type="button" onClick={() => onRemoveFolder(folder.id)} aria-label={`Remove ${folder.path}`} title="Remove">
                    <Icon name="trash" size={14} />
                  </button>
                </li>
              ))}
            </ul>
          )}

          <h3 className="project-dialog__section">Files</h3>
          <p className="folders-dialog__empty">
            {project.file_count === 0 ? 'No files catalogued yet.' : `${project.file_count.toLocaleString()} files catalogued.`}
          </p>
        </>
      )}

      {shownMessage && (
        <p className={`folders-dialog__message folders-dialog__message--${shownMessage.kind}`} role={shownMessage.kind === 'error' ? 'alert' : 'status'}>
          {shownMessage.text}
        </p>
      )}

      {!creating && project && (
        <footer className="folders-dialog__actions">
          <button className="folders-dialog__button" type="button" onClick={onScanFiles} disabled={project.folders.length === 0}>
            Scan files
          </button>
          <button className="folders-dialog__button folders-dialog__button--primary" type="button" onClick={onAddFolder}>
            <Icon name="plus" /> Add folder…
          </button>
        </footer>
      )}
    </dialog>
  )
}
