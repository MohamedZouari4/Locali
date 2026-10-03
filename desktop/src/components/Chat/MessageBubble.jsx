// One chat message, with source chips that reveal the cited file when clicked.
// User messages are right-aligned bubbles; Locali's answers sit next to its mark, without a bubble.

import { BrandMark, Icon } from '../Icon'

export function MessageBubble({ message, onRetry }) {
  const { role, text, isStreaming, sources, error, stopped, incomplete } = message

  if (role === 'user') {
    return (
      <article className="message message--user" aria-label="You">
        <div className="message__bubble">{text}</div>
      </article>
    )
  }

  return (
    <article className="message message--assistant" aria-label="Locali">
      <BrandMark size={26} />
      <div className="message__body">
        {text ? (
          <div className="message__text">
            {text}
            {isStreaming && <span className="message__cursor" aria-hidden="true" />}
          </div>
        ) : (
          isStreaming && (
            <div className="thinking">
              <i /><i /><i />
              <span className="visually-hidden">Thinking</span>
            </div>
          )
        )}
        {stopped && <p className="message__note">Stopped</p>}
        {incomplete && <p className="message__note">This answer was interrupted and is incomplete.</p>}
        {error && (
          <div className="message__error" role="alert">
            <Icon name="alert" />
            <span>{error}</span>
            {onRetry && (
              <button type="button" className="message__retry" onClick={onRetry}>
                <Icon name="retry" size={13} /> Retry
              </button>
            )}
          </div>
        )}
        {sources?.length > 0 && (
          <div className="citations" aria-label="Sources">
            <span className="citations__label">Sources</span>
            {sources.map((source) => {
              const sourcePath = typeof source === 'string' ? source : source.path
              const sourceName = typeof source === 'string' ? source.split(/[\\/]/).pop() : source.filename ?? source.path

              return (
                <button
                  key={sourcePath}
                  type="button"
                  className="citation-chip"
                  onClick={() => window.localiAPI.files.reveal(sourcePath)}
                  title={`Reveal ${sourcePath}`}
                >
                  <Icon name="file" size={13} />
                  <span>{sourceName}</span>
                </button>
              )
            })}
          </div>
        )}
      </div>
    </article>
  )
}
