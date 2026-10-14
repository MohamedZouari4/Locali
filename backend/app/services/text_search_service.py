"""Full-text search over the text cache: words and phrases in a project's catalogued files.

The index is SQLite's built-in FTS5 (the text_search table), which triggers keep in step with the cache,
so text can be found as soon as it is cached and is gone once it is pruned. The index holds each part's
search terms (app/core/text_terms.py), the same terms keyword search uses, so words match in any script,
whatever their case, accents or Arabic letter forms. Words match in any order and "quoted words" match as
a phrase. Each hit gives the file, the PDF page (None for other files, which are cached as one section) and
a snippet of the original text with the matches marked **so**.

Only text already in the cache is searched: a file that hasn't been read yet isn't found, and a file
changed since its last read is found by its old text until it is read again. What the user types is
reduced to search terms, which hold only letters and digits, before it reaches FTS5, so AND, NEAR, * or a
stray quote are searched for as words or dropped, never run as query syntax.
"""

import re

from app.ai.ingestion.extractors import EXTRACTOR_VERSION
from app.core.text_terms import terms, tokenize
from app.db import database

# A "quoted phrase", or a run of anything but spaces.
TERM_RE = re.compile(r'"([^"]*)"|(\S+)')
MAX_HITS = 50
# How many terms of text a snippet shows around the first match.
SNIPPET_TERMS = 16


def search(project_id, query, limit=20):
    """The project's best full-text hits for `query`, best first, as {"file_id", "name", "path", "page",
    "snippet"}, at most `limit` of them (up to MAX_HITS). A query without words finds nothing."""
    match = _match_expression(query)
    if not match:
        return []
    rows = database.search_text(project_id, match, EXTRACTOR_VERSION, max(1, min(limit, MAX_HITS)))
    wanted = set(tokenize(query))
    return [
        {
            "file_id": row["file_id"],
            "name": row["name"],
            "path": row["path"],
            "page": row["part"] if row["unit"] == "page" else None,
            "snippet": _snippet(row["text"], wanted),
        }
        for row in rows
    ]


def _match_expression(query):
    """The query in FTS5 syntax: the search terms of every word and "quoted phrase", each quoted as a phrase
    so it must appear."""
    phrases = [tokenize(phrase or word) for phrase, word in TERM_RE.findall(query)]
    return " ".join('"' + " ".join(phrase) + '"' for phrase in phrases if phrase)


def _snippet(text, wanted):
    """Up to SNIPPET_TERMS terms of `text` from just before its first match, with each run of matching terms
    between ** marks and … where text was cut. The text is shown as written, not as folded terms."""
    found = terms(text)
    hits = [index for index, (term, _, _) in enumerate(found) if term in wanted]
    if not hits:
        return ""
    first = max(0, min(hits[0] - SNIPPET_TERMS // 4, len(found) - SNIPPET_TERMS))
    last = min(first + SNIPPET_TERMS, len(found)) - 1
    start = 0 if first == 0 else found[first][1]
    end = len(text) if last == len(found) - 1 else found[last][2]
    pieces, cursor = [], start
    for index in range(first, last + 1):
        term, term_start, term_end = found[index]
        if term not in wanted:
            continue
        if index == first or found[index - 1][0] not in wanted:
            pieces += [text[cursor:term_start], "**"]
            cursor = term_start
        if index == last or found[index + 1][0] not in wanted:
            pieces += [text[cursor:term_end], "**"]
            cursor = term_end
    pieces.append(text[cursor:end])
    return ("…" if first > 0 else "") + "".join(pieces).strip() + ("…" if end < len(text.rstrip()) else "")
