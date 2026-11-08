"""File details: one catalogued file's metadata, what its text says about its length, and for an image the
text OCR finds in it.

Size and dates come from the catalog, so they are as fresh as the last scan or watcher update. Pages,
sections, lines and OCR text come from the text cache through reader_service, which checks the project's
folders, sensitive names, size and file type before opening the file, and redacts the text before storing
it. A file whose text can't be read still gets its metadata, with the code and the reason, because a
details question shouldn't fail on a zip or a damaged file.
"""

from app.ai.ingestion.extractors import IMAGE_EXTENSIONS, get_source_type
from app.db import database
from app.services import reader_service, text_cache_service


def file_details(project_id, file_id):
    """{"file_id", "name", "path", "extension", "kind", "size", "created", "modified", "catalogued"} (dates in
    UTC as the catalog stores them), plus "pages" for a PDF, "sections" for Markdown or Word, "lines"
    otherwise, "characters", and for an image "ocr_text" and "ocr_truncated". When the text can't be read,
    "text_unavailable" holds {"code", "message"} instead. Returns None if the file isn't in the project's catalog."""
    file = database.get_catalog_file(project_id, file_id)
    if file is None:
        return None
    details = {
        "file_id": file["id"],
        "name": file["name"],
        "path": file["path"],
        "extension": file["extension"],
        "kind": get_source_type(file["extension"]),
        "size": file["size"],
        "created": file["file_created_at"],
        "modified": file["file_modified_at"],
        "catalogued": file["catalogued_at"],
    }
    try:
        # With no part named, read_part reads from the start and returns the file's totals.
        part = reader_service.read_part(project_id, file_id)
    except text_cache_service.TextUnavailable as error:
        return {**details, "text_unavailable": {"code": error.code, "message": str(error)}}
    except reader_service.PartNotFound as error:  # a PDF with no pages
        return {**details, "text_unavailable": {"code": "unreadable", "message": str(error)}}
    if part["total_pages"] is not None:
        details["pages"] = part["total_pages"]
    elif part["total_sections"] is not None:
        details["sections"] = part["total_sections"]
    else:
        details["lines"] = part["total_lines"]  # for a PDF this would only count page 1, so it's left out there
    details["characters"] = part["total_chars"]
    if file["extension"] in IMAGE_EXTENSIONS:
        details["ocr_text"] = part["text"]
        details["ocr_truncated"] = part["truncated"]
    return details
