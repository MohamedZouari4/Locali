// Project dialog. In create mode it asks for a name, instructions and folders: Create project, or Add
// folder… (which creates the project first, then opens the folder picker); either way the chat screen
// then switches to the new project and closes the dialog. In settings mode it edits the current project:
// its folders with their Read/Act permission, Add folder… and Remove, how many files the catalog holds,
// with Scan files, and Delete… at the bottom (the chat screen asks for confirmation; the last project
// can't be deleted). Uses the native <dialog> element, like the Indexed folders dialog.
//
// The chat screen gives the dialog a new key each time it opens, so the form starts fresh.

import { useEffect, useRef, useState } from 'react'
import { Icon } from '../Icon'

// One pattern per line; blank lines are dropped (the backend also trims and removes duplicates).
function toPatterns(text) {
  return text
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
}

const skipLabels = [
  ['folders', 'dependency, cache and system folders'],
  ['sensitive', 'files with keys or credentials'],
  ['binary', 'programs, archives and media'],
  ['too_large', 'large files'],
  ['project_rules', 'by your ignore patterns'],
]

// "Skipped 12 dependency, cache and system folders · 3 files with keys or credentials", or null.
function skippedSummary(skipped) {
  const parts = skipLabels.filter(([key]) => skipped?.[key]).map(([key, label]) => `${skipped[key].toLocaleString()} ${label}`)
  return parts.length ? `Skipped ${parts.join(' · ')}.` : null
}

const permissions = [
  { value: 'read', label: 'Read', hint: 'Locali may search this folder.' },
  { value: 'act', label: 'Act', hint: 'Locali may also change files in this folder.' },
]

// Electron prefixes errors from the main process; keep only the backend's message.
function readable(error) {
  return String(error?.message ?? error).replace(/^Error invoking remote method '[^']+': (Error: )?/, '')
}

export function ProjectDialog({
  open,
  mode,
  project,
  message,
  canDelete,
  onClose,
  onCreate,
  onSave,
  onAddFolder,
  onSetPermission,
  onRemoveFolder,
  onScanFiles,
  onDelete,
}) {
  const creating = mode === 'create'
  const dialogRef = useRef(null)
  // null until edited: the field then shows the project's saved value, which may still be loading.
  const [draftName, setDraftName] = useState(null)
  const [draftInstructions, setDraftInstructions] = useState(null)
  const [draftIgnore, setDraftIgnore] = useState(null)
  const [createError, setCreateError] = useState(null)
  const [busy, setBusy] = useState(false)
  const name = draftName ?? (creating ? '' : (project?.name ?? ''))
  const instructions = draftInstructions ?? (creating ? '' : (project?.instructions ?? ''))
  const ignoreText = draftIgnore ?? (project?.ignore_patterns ?? []).join('\n')

  useEffect(() => {
    const dialog = dialogRef.current
    if (open && !dialog.open) dialog.showModal()
    if (!open && dialog.open) dialog.close()
  }, [open])

  // Returns the new project, or null if it couldn't be created (the reason is shown).
  const create = async () => {
    setBusy(true)
    try {
      return await onCreate(name.trim(), instructions)
    } catch (error) {
      setCreateError(readable(error))
      return null
    } finally {
      setBusy(false)
    }
  }

  const submit = async (event) => {
    event.preventDefault()
    if (!name.trim() || busy) return
    if (creating) await create()
    else onSave(name.trim(), instructions, toPatterns(ignoreText))
  }

  const createAndAddFolder = async () => {
    if (!name.trim() || busy) return
    const created = await create()
    if (created) await onAddFolder(created.id)
  }

  const unchanged =
    !creating &&
    project &&
    name.trim() === project.name &&
    instructions === project.instructions &&
    toPatterns(ignoreText).join('\n') === project.ignore_patterns.join('\n')
  const shownMessage = creating ? (createError ? { kind: 'error', text: createError } : null) : message
  const folders = creating ? [] : (project?.folders ?? [])
  // In create mode Add folder… creates the project first.
  const addFolder = creating ? createAndAddFolder : () => onAddFolder()

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

      {/* At the top, so the outcome of the last action is the first thing seen. */}
      {shownMessage && (
        <p className={`folders-dialog__message folders-dialog__message--${shownMessage.kind}`} role={shownMessage.kind === 'error' ? 'alert' : 'status'}>
          {shownMessage.kind === 'success' && <Icon name="check" size={15} />}
          {shownMessage.text}
        </p>
      )}

      <form className="project-dialog__form" onSubmit={submit}>
        <label className="project-dialog__field">
          <span>Name</span>
          <input value={name} onChange={(event) => setDraftName(event.target.value)} maxLength={100} required autoFocus />
        </label>
        <label className="project-dialog__field">
          <span>Instructions</span>
          <textarea
            value={instructions}
            onChange={(event) => setDraftInstructions(event.target.value)}
            maxLength={20000}
            rows={3}
            placeholder="For example: answer in French, and cite the file names."
          />
        </label>
        {!creating && (
          <label className="project-dialog__field">
            <span>Ignore</span>
            <textarea
              value={ignoreText}
              onChange={(event) => setDraftIgnore(event.target.value)}
              rows={3}
              spellCheck={false}
              className="project-dialog__patterns"
              placeholder={'One pattern per line, for example:\n*.log\ndrafts/\ndata/raw/*.csv'}
            />
            <small>
              Added to what Locali always skips: dependency and cache folders, files with keys or credentials, programs and
              media, and large files.
            </small>
          </label>
        )}
        {/* Save only appears once something changed; Create project is always there. */}
        {(creating || (project && !unchanged)) && (
          <div className="folders-dialog__actions">
            <button className="folders-dialog__button folders-dialog__button--primary" type="submit" disabled={!name.trim() || busy}>
              {creating ? 'Create project' : 'Save changes'}
            </button>
          </div>
        )}
      </form>

      {(creating || project) && (
        <section className="project-dialog__group">
          <div className="project-dialog__section-header">
            <h3 className="project-dialog__section">Folders</h3>
            {folders.length > 0 && (
              <button className="folders-dialog__button folders-dialog__button--small" type="button" onClick={addFolder}>
                <Icon name="plus" size={14} /> Add folder…
              </button>
            )}
          </div>
          {folders.length === 0 ? (
            <div className="project-dialog__empty-folders">
              <span className="project-dialog__empty-icon"><Icon name="folder" size={20} /></span>
              <div>
                <strong>No folders yet</strong>
                <small>{creating ? 'Choose the folders this project uses. You can add more later.' : 'Add the folders this project uses so Locali can find its files.'}</small>
              </div>
              <button className="folders-dialog__button folders-dialog__button--primary" type="button" onClick={addFolder} disabled={busy || (creating && !name.trim())}>
                <Icon name="plus" /> Add folder…
              </button>
            </div>
          ) : (
            <ul className="folders-dialog__list">
              {folders.map((folder) => (
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
        </section>
      )}

      {/* Files only means something once there is a folder to scan. */}
      {!creating && folders.length > 0 && (
        <section className="project-dialog__group project-dialog__files">
          <div>
            <h3 className="project-dialog__section">Files</h3>
            <small>{project.file_count === 0 ? 'Not scanned yet.' : `${project.file_count.toLocaleString()} files catalogued.`}</small>
            {skippedSummary(project.catalog_skipped) && <small className="project-dialog__skipped">{skippedSummary(project.catalog_skipped)}</small>}
          </div>
          <button className="folders-dialog__button folders-dialog__button--small" type="button" onClick={() => onScanFiles()}>
            Scan files
          </button>
        </section>
      )}

      {!creating && project && (
        <section className="project-dialog__danger">
          <div>
            <strong>Delete project</strong>
            <small>{canDelete ? 'Deletes its chats, folder list and file catalog. Files in its folders are never touched.' : 'Locali needs at least one project, so the last one can’t be deleted.'}</small>
          </div>
          <button className="project-dialog__delete" type="button" onClick={onDelete} disabled={!canDelete}>
            Delete…
          </button>
        </section>
      )}
    </dialog>
  )
}
