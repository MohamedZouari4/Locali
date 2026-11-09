// Renders the small part of Markdown the chat model writes: headings, paragraphs, bullet and numbered lists,
// fenced code blocks, and inline **bold**, *italic* and `code`. It builds React elements and never HTML, so
// text from the model or from a user's file can't inject markup, and anything it doesn't recognise stays
// plain text. While an answer streams, an unclosed code block shows as code until its closing fence arrives.

const FENCE = /^\s*(```|~~~)/
const HEADING = /^(#{1,6})\s+(.+)$/
const BULLET = /^\s*[-*•]\s+(.*)$/
const NUMBERED = /^\s*(\d+)[.)]\s+(.*)$/
const INLINE = /(`[^`\n]+`|\*\*[^*\n]+\*\*|\*[^*\s][^*\n]*\*)/

function startsBlock(line) {
  return FENCE.test(line) || HEADING.test(line) || BULLET.test(line) || NUMBERED.test(line)
}

// The text as blocks: { type: 'code' | 'h3' | 'h4' | 'ul' | 'ol' | 'p', text?, items?, start? }.
function parse(text) {
  const lines = text.split('\n')
  const blocks = []
  let i = 0
  while (i < lines.length) {
    const line = lines[i]
    if (FENCE.test(line)) {
      const code = []
      i += 1
      while (i < lines.length && !FENCE.test(lines[i])) code.push(lines[i++])
      i += 1 // the closing fence, once it has arrived
      blocks.push({ type: 'code', text: code.join('\n') })
    } else if (HEADING.test(line)) {
      const [, hashes, title] = line.match(HEADING)
      blocks.push({ type: hashes.length <= 2 ? 'h3' : 'h4', text: title })
      i += 1
    } else if (BULLET.test(line) || NUMBERED.test(line)) {
      const pattern = BULLET.test(line) ? BULLET : NUMBERED
      const items = []
      while (i < lines.length && pattern.test(lines[i])) {
        const match = lines[i++].match(pattern)
        items.push(match[match.length - 1])
      }
      blocks.push({ type: pattern === BULLET ? 'ul' : 'ol', start: pattern === NUMBERED ? Number(line.match(NUMBERED)[1]) : undefined, items })
    } else if (!line.trim()) {
      i += 1
    } else {
      const paragraph = []
      while (i < lines.length && lines[i].trim() && !startsBlock(lines[i])) paragraph.push(lines[i++])
      blocks.push({ type: 'p', text: paragraph.join('\n') })
    }
  }
  return blocks
}

// Splitting on a pattern with one capture group puts the matches at the odd indexes.
function inline(text) {
  return text.split(INLINE).map((part, index) => {
    if (index % 2 === 0) return part
    if (part.startsWith('`')) return <code key={index}>{part.slice(1, -1)}</code>
    if (part.startsWith('**')) return <strong key={index}>{part.slice(2, -2)}</strong>
    return <em key={index}>{part.slice(1, -1)}</em>
  })
}

export function Markdown({ text }) {
  return parse(text).map((block, index) => {
    switch (block.type) {
      case 'code':
        return <pre key={index} className="md-code"><code>{block.text}</code></pre>
      case 'h3':
        return <h3 key={index} className="md-heading">{inline(block.text)}</h3>
      case 'h4':
        return <h4 key={index} className="md-heading md-heading--small">{inline(block.text)}</h4>
      case 'ul':
        return <ul key={index} className="md-list">{block.items.map((item, n) => <li key={n}>{inline(item)}</li>)}</ul>
      case 'ol':
        return <ol key={index} className="md-list" start={block.start}>{block.items.map((item, n) => <li key={n}>{inline(item)}</li>)}</ol>
      default:
        return <p key={index} className="md-paragraph">{inline(block.text)}</p>
    }
  })
}
