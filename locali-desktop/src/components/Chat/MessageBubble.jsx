export function MessageBubble({ message }) {
  const { role, text, isStreaming, sources } = message

  return (
    <article className={`bubble bubble--${role}`}>
      <div className="bubble__meta">{role === 'user' ? 'You' : 'Locali'}<span>{role === 'assistant' && ' · Local'}</span></div>
      <div className="bubble__text">
        {text || (isStreaming ? 'Thinking' : '')}
        {isStreaming && (
          <span className="bubble__cursor" aria-hidden="true" />
        )}
      </div>
      {sources?.length > 0 && (
        <div className="bubble__citations" aria-label="Sources">
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
              {sourceName}
            </button>
            )
          })}
        </div>
      )}
    </article>
  )
}
