"""Text cache: the extracted text of a project's catalogued files, read once per version of their content.

A file's text is looked up by the SHA-256 of its bytes, its extension (which picks the reader) and
EXTRACTOR_VERSION, so an unchanged file is never extracted twice, a changed file is extracted again on its
next read, and the same file in several projects shares one entry. The text is redacted before it is
Every part is also in the full-text index, which the database keeps in step (text_search_service).

The file is found through the project's catalog and checked against the project's folders
(project_boundary) before it is opened, so a link swapped in after the scan can't lead outside them.
Each catalog row records the content its text was last read from (text_hash); cached text no row
points to is pruned after every full catalog scan and when a project is deleted.
"""

import os

from app.ai.ingestion.extractors import EXTRACTOR_VERSION, extract_parts, sniff_mime
from app.ai.ingestion.pipeline import file_hash
from app.ai.ingestion.redaction import redact_pii
from app.ai.ingestion.walker import is_sensitive
from app.core import config
from app.db import database
from app.services import project_boundary, project_service


class TextUnavailable(Exception):
    """The file can't be read as text: it is gone, outside the project's folders, too large, unsafe or unsupported."""


def read_text(project_id, file_id):
    """The text of one catalogued file as {"file_id", "unit", "parts"}: "page" parts for a PDF, one
    "section" otherwise. Returns None if the file isn't in the project's catalog; raises TextUnavailable."""
    file = database.get_catalog_file(project_id, file_id)
    if file is None:
        return None
    try:
        path, _folder = project_service.check_path(project_id, file["path"])
    except project_boundary.PathRefused as error:
        raise TextUnavailable(str(error)) from None
    if is_sensitive(file["name"]):  # the catalog skips these too; checked again in case the rules changed
        raise TextUnavailable(f"{file['name']} may hold keys or credentials, so Locali never opens it.")
    try:
        content_hash = _checked_hash(path, file)
    except OSError as error:
        raise TextUnavailable(f"{file['name']} can't be read: {error.strerror or error}") from None

    # Recorded before the text is saved, so a prune running in between never removes it.
    database.set_catalog_text_hash(file["id"], content_hash)
    cached = database.get_cached_text(content_hash, file["extension"], EXTRACTOR_VERSION)
    if cached is None:
        cached = _extract(path, file["name"])
        # A file saved again while it was read: the text belongs to the new content, so it isn't cached
        # under the old hash, and the next read extracts it again.
        if _same_content(path, content_hash):
            database.save_cached_text(content_hash, file["extension"], EXTRACTOR_VERSION, *cached)
    unit, parts = cached
    return {"file_id": file["id"], "unit": unit, "parts": parts}


def _checked_hash(path, file):
    """The file's SHA-256, after the same size and file-type checks ingestion makes."""
    if os.path.getsize(path) > config.MAX_FILE_SIZE_MB * 1024 * 1024:
        raise TextUnavailable(f"{file['name']} is larger than {config.MAX_FILE_SIZE_MB} MB.")
    kind, safe = sniff_mime(path, file["extension"])
    if not safe:
        raise TextUnavailable(f"{file['name']} doesn't look like a .{file['extension']} file (it reads as {kind}).")
    return file_hash(path)


def _extract(path, name):
    try:
        extracted = extract_parts(path)
    except Exception as error:  # a damaged file: each reader raises its own kind of error
        raise TextUnavailable(f"{name} can't be read: {error}") from None
    if extracted is None:
        raise TextUnavailable(f"Locali can't read text from {name}.")
    unit, parts = extracted
    return unit, [redact_pii(part.encode("utf-8", "ignore").decode("utf-8"))[0] for part in parts]


def _same_content(path, content_hash):
    try:
        return file_hash(path) == content_hash
    except OSError:  # deleted while it was read
        return False
