// A short confirmation at the bottom of the window ("Chat renamed"), green with a check mark. It is
// announced politely to screen readers, and the chat screen hides it again after a few seconds.

import { Icon } from '../Icon'

export function Toast({ toast }) {
  return (
    <div className="toast-region" role="status" aria-live="polite">
      {toast && (
        // A new key per toast replays the entrance even when the text is the same.
        <div className="toast" key={toast.id}>
          <span className="toast__icon"><Icon name="check" size={14} /></span>
          {toast.text}
        </div>
      )}
    </div>
  )
}
