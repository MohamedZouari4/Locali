// Confirmation dialog in the app's own style, used instead of window.confirm (which shows a bare system
// box titled with the package name). Uses the native <dialog> element: Esc or the backdrop cancels, and
// focus starts on Cancel, so pressing Enter by accident never deletes anything.

import { useEffect, useRef } from 'react'
import { Icon } from '../Icon'

export function ConfirmDialog({ open, title, message, confirmLabel = 'Delete', icon = 'trash', onConfirm, onCancel }) {
  const dialogRef = useRef(null)
  const cancelRef = useRef(null)

  useEffect(() => {
    const dialog = dialogRef.current
    if (open && !dialog.open) {
      dialog.showModal()
      cancelRef.current?.focus()
    }
    if (!open && dialog.open) dialog.close()
  }, [open])

  // A click on the backdrop lands on the <dialog> element itself, outside its content box.
  const cancelOnBackdrop = (event) => {
    if (event.target === dialogRef.current) onCancel()
  }

  return (
    <dialog
      ref={dialogRef}
      className="folders-dialog confirm-dialog"
      role="alertdialog"
      aria-labelledby="confirm-dialog-title"
      aria-describedby="confirm-dialog-message"
      onClose={onCancel}
      onClick={cancelOnBackdrop}
    >
      <div className="confirm-dialog__body">
        <span className="confirm-dialog__icon"><Icon name={icon} size={18} /></span>
        <div>
          <h2 id="confirm-dialog-title">{title}</h2>
          <p id="confirm-dialog-message">{message}</p>
        </div>
      </div>
      <footer className="folders-dialog__actions">
        <button ref={cancelRef} className="folders-dialog__button" type="button" onClick={onCancel}>
          Cancel
        </button>
        <button className="folders-dialog__button folders-dialog__button--danger" type="button" onClick={onConfirm}>
          {confirmLabel}
        </button>
      </footer>
    </dialog>
  )
}
