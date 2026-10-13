"""Full-text search over the text cache: words and phrases in a project's catalogued files.

The index is SQLite's built-in FTS5 (the text_search table), which triggers keep in step with the cache,
so text can be found as soon as it is cached and is gone once it is pruned. Words match in any order,
case and accents aside, and "quoted words" match as a phrase. Each hit gives the file, the PDF page
(None for other files, which are cached as one section) and a snippet with the matches marked **so**.

Only text already in the cache is searched: a file that hasn't been read yet isn't found, and a file
changed since its last read is found by its old text until it is read again. Each word the user types is
quoted before it reaches FTS5, so AND, NEAR, * or a stray quote are searched for as words, never run as
query syntax.
"""

import re

from app.ai.ingestion.extractors import EXTRACTOR_VERSION
from app.db import database

# A "quoted phrase", or a run of anything but spaces.
TERM_RE = re.compile(r'"([^"]*)"|(\S+)')
MAX_HITS = 50


def search(project_id, query, limit=20):
    """The project's best full-text hits for `query`, best first, as {"file_id", "name", "path", "page",
    "snippet"}, at most `limit` of them (up to MAX_HITS). A query without words finds nothing."""
    match = _match_expression(query)
    if not match:
        return []
    rows = database.search_text(project_id, match, EXTRACTOR_VERSION, max(1, min(limit, MAX_HITS)))
    return [
        {
            "file_id": row["file_id"],
            "name": row["name"],
            "path": row["path"],
            "page": row["part"] if row["unit"] == "page" else None,
            "snippet": row["snippet"],
        }
        for row in rows
    ]


def _match_expression(query):
    """The query in FTS5 syntax: every word and phrase quoted, so each one must appear."""
    terms = [phrase or word for phrase, word in TERM_RE.findall(query)]
    return " ".join('"' + term.replace('"', '""') + '"' for term in terms if term.strip())
