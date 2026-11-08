"""Full-text search over the text cache: words and phrases in a project's catalogued files.

The index is SQLite's built-in FTS5 (the text_search table), which triggers keep in step with the cache,
so text can be found as soon as it is cached and is gone once it is pruned. The index holds each part's
search terms (app/core/text_terms.py), the same terms keyword search uses, so words match in any script,
whatever their case, accents or Arabic letter forms. Words match in any order and "quoted words" match as
a phrase. Each hit gives the file, the PDF page (None for other files, which are cached as one section) and
a snippet of the original text with the matches marked **so**.

Only text already in the cache is searched, so read_unread_files first reads the project's small files that
aren't cached yet (code, Markdown, text, CSV, PDF and Word up to 1 MB; no images, which need slow OCR), within
a short time budget, and says how many it had to leave for later. A file it didn't get to isn't found, and a
file changed since its last read is found by its old text until it is read again. Each hit also gives the line of the
first match in a file cached as one section, so the Read file tool can open it there. What the user types is
reduced to search terms, which hold only letters and digits, before it reaches FTS5, so AND, NEAR, * or a
stray quote are searched for as words or dropped, never run as query syntax.
"""

import logging
import re
import time

from app.ai.ingestion.extractors import EXTRACTOR_VERSION
from app.core import config
from app.core.text_terms import terms, tokenize
from app.db import database
from app.services import text_cache_service

log = logging.getLogger(__name__)

# A "quoted phrase", or a run of anything but spaces.
TERM_RE = re.compile(r'"([^"]*)"|(\S+)')
MAX_HITS = 50
# How many terms of text a snippet shows around the first match.
SNIPPET_TERMS = 16
# read_unread_files reads files of these types up to this size, for at most this long per search.
SMALL_FILE_EXTENSIONS = config.CODE_EXTENSIONS | {"csv", "pdf", "docx"}
SMALL_FILE_MAX_BYTES = 1024 * 1024
READ_BUDGET_SECONDS = 2.0


def search(project_id, query, limit=20):
    """The project's best full-text hits for `query`, best first, as {"file_id", "name", "path", "page",
    "line", "snippet"}, at most `limit` of them (up to MAX_HITS): `page` for a PDF, `line` (of the first
    match) for every other file. A query without words finds nothing."""
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
            "line": _first_line(row["text"], wanted) if row["unit"] != "page" else None,
            "snippet": _snippet(row["text"], wanted),
        }
        for row in rows
    ]


def read_unread_files(project_id, clock=time.monotonic):
    """Reads the project's small files whose current text isn't cached yet into the cache, newest first, until
    READ_BUDGET_SECONDS are spent. Returns {"read", "left"}: how many were read, and how many small files are
    still unread because the time ran out. A file that can't be read is skipped; the search doesn't find it."""
    deadline = clock() + READ_BUDGET_SECONDS
    files = database.list_uncached_files(EXTRACTOR_VERSION, SMALL_FILE_MAX_BYTES, SMALL_FILE_EXTENSIONS, (), 500, project_id)
    read = tried = 0
    for file in files:
        if clock() >= deadline:
            break
        tried += 1
        try:
            text_cache_service.read_text(project_id, file["id"])
            read += 1
        except text_cache_service.TextUnavailable as error:
            log.info("Not searched: %s", error)
    return {"read": read, "left": len(files) - tried}


def _first_line(text, wanted):
    # The line number (from 1) of the first term of `text` the query asked for.
    for term, start, _ in terms(text):
        if term in wanted:
            return text.count("\n", 0, start) + 1
    return None


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
