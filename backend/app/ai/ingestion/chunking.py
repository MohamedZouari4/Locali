"""Splits extracted text into chunks: one per ALL-CAPS section, with sections longer than
MAX_SECTION_CHARS cut on paragraph breaks. Each chunk carries its metadata envelope.
"""

import hashlib
import re

from app.ai.ingestion.extractors import count_tokens, detect_language

MAX_SECTION_CHARS = 4000

_HEADER_RE = re.compile(r"^\s*(?:[*#_]+\s*)?([A-Z][A-Z \-&]{2,40})\s*(?:[*#_]+\s*)?$", re.MULTILINE)


def make_document_id(content_hash: str) -> str:
    """Return a stable identifier derived from file content."""
    return content_hash[:16]


def split_large_section(body, max_chars=MAX_SECTION_CHARS):
    if len(body) <= max_chars:
        return [body]
    paragraphs = re.split(r"\n\s*\n", body)
    parts, current = [], ""
    for paragraph in paragraphs:
        candidate = f"{current}\n\n{paragraph}" if current else paragraph
        if len(candidate) > max_chars and current:
            parts.append(current)
            current = paragraph
        else:
            current = candidate
        while len(current) > max_chars:
            parts.append(current[:max_chars])
            current = current[max_chars:]
    if current:
        parts.append(current)
    return parts


def chunk_by_section(text: str, doc_id: str, source: str, file_type: str, source_type: str):
    """Split sections and pre-split oversized sections into child chunks."""
    sections, last_end, last_header = [], 0, "GENERAL"
    for match in _HEADER_RE.finditer(text):
        if match.start() > last_end:
            sections.append((last_header, text[last_end : match.start()].strip()))
        last_header, last_end = match.group(1).strip(), match.end()
    sections.append((last_header, text[last_end:].strip()))
    sections = [(section, body) for section, body in sections if body]

    expanded = []
    for section, body in sections:
        parts = split_large_section(body)
        for part_index, part_body in enumerate(parts):
            heading_path = section if len(parts) == 1 else f"{section} > part {part_index + 1}"
            expanded.append((section, heading_path, part_body))

    total = len(expanded)
    source_id = hashlib.sha256(source.encode("utf-8")).hexdigest()[:8]
    chunks = []
    for index, (section, heading_path, body) in enumerate(expanded):
        chunks.append(
            {
                "chunk_id": f"{doc_id}_{source_id}_{index:02d}",
                "document_id": doc_id,
                "section": section,
                "heading_path": heading_path,
                "chunk_index": index,
                "total_chunks": total,
                "source": source,
                "file_type": file_type,
                "source_type": source_type,
                "language": detect_language(body, file_type),
                "sensitivity": None,
                "token_count": count_tokens(body),
                "text": body,
            }
        )
    return chunks
