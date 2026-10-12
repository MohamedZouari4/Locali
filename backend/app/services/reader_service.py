"""Reading a catalogued file in parts, so a large file fits the model's context.

The text comes from the text cache (text_cache_service), so each version of a file is extracted once
however many parts are read. A PDF is read by page; Markdown and Word files by section, where a heading
starts a section (Word headings arrive as Markdown headings, and each Word paragraph is one line); any
file by line range. A page or section can also be read from a given line onward.

Every read returns at most MAX_READ_CHARS, cut at a line boundary, with the line it stopped at and the
file's totals (pages, sections, lines, characters), so the agent knows what remains and where to go on.
A single line longer than the cap is cut and marked truncated.
"""

import re

from app.core import config
from app.db import database
from app.services import text_cache_service

# Files whose headings split them into sections: Markdown, and Word once its headings are marked up.
SECTION_EXTENSIONS = {"md", "docx"}
HEADING_RE = re.compile(r"^#{1,6}\s+\S")
FENCE_RE = re.compile(r"^\s*(```|~~~)")


class PartNotFound(ValueError):
    """The page, section or lines asked for don't exist in this file, or this file isn't read that way."""


def read_part(project_id, file_id, *, page=None, section=None, start_line=None, end_line=None):
    """One part of a catalogued file's text. A PDF takes `page` (default 1); any other file takes
    `section` (Markdown and Word only) or a line range, or neither to read from its start. `start_line`
    and `end_line` (inclusive) count from the top of the page, or of the file otherwise.

    Returns None if the file isn't in the project's catalog. Raises PartNotFound, or
    text_cache_service.TextUnavailable when the file can't be read at all.
    """
    file = database.get_catalog_file(project_id, file_id)
    if file is None:
        return None
    text = text_cache_service.read_text(project_id, file_id)
    parts = text["parts"]
    result = {"file_id": file_id, "name": file["name"], "unit": "lines", "page": None, "section": None, "title": None}
    totals = {"total_pages": None, "total_sections": None, "total_chars": sum(len(part) for part in parts)}

    if text["unit"] == "page":
        if section is not None:
            raise PartNotFound(f"{file['name']} is a PDF, so it is read by page, not by section.")
        page = 1 if page is None else page
        if not 1 <= page <= len(parts):
            raise PartNotFound(f"{file['name']} has {len(parts)} pages; there is no page {page}.")
        lines = parts[page - 1].splitlines()
        first, last = 1, len(lines)
        result.update(unit="page", page=page)
        totals["total_pages"] = len(parts)
    else:
        if page is not None:
            raise PartNotFound(f"Only a PDF is read by page; read {file['name']} by section or by lines.")
        lines = parts[0].splitlines()
        first, last = 1, len(lines)
        if file["extension"] in SECTION_EXTENSIONS:
            sections = _sections(lines)
            totals["total_sections"] = len(sections)
            if section is not None:
                if not 1 <= section <= len(sections):
                    raise PartNotFound(f"{file['name']} has {len(sections)} sections; there is no section {section}.")
                title, first, last = sections[section - 1]
                result.update(unit="section", section=section, title=title)
        elif section is not None:
            raise PartNotFound(f"{file['name']} has no sections; read it by lines.")

    window = _window(lines, first, last, start_line, end_line, file["name"])
    return {**result, **window, "total_lines": len(lines), **totals}


def _sections(lines):
    """(title, first line, last line) of each section. A heading line starts one; lines before the first
    heading form a section without a title. Lines inside ``` or ~~~ code blocks are never headings."""
    starts, fenced = [], False
    for number, line in enumerate(lines, start=1):
        if FENCE_RE.match(line):
            fenced = not fenced
        elif not fenced and HEADING_RE.match(line):
            starts.append(number)
    if not starts or starts[0] != 1:
        starts.insert(0, 1)
    sections = []
    for index, first in enumerate(starts):
        last = starts[index + 1] - 1 if index + 1 < len(starts) else len(lines)
        heading = lines[first - 1] if first <= len(lines) else ""
        title = heading.lstrip("#").strip() if HEADING_RE.match(heading) else None
        sections.append((title, first, last))
    return sections


def _window(lines, first, last, start_line, end_line, name):
    """Lines start_line to end_line, kept within first to last and capped at MAX_READ_CHARS."""
    start = first if start_line is None else start_line
    if not first <= start <= max(last, first):
        raise PartNotFound(f"Line {start} is outside lines {first} to {last} of {name}.")
    stop = last if end_line is None else min(end_line, last)
    if stop < start - 1:
        raise PartNotFound(f"end_line {end_line} comes before start_line {start}.")
    chosen, size, cut = [], 0, False
    for number in range(start, stop + 1):
        line = lines[number - 1]
        if chosen and size + len(line) + 1 > config.MAX_READ_CHARS:
            break
        if len(line) > config.MAX_READ_CHARS:  # one very long line, such as minified code
            line, cut = line[: config.MAX_READ_CHARS], True
        chosen.append(line)
        size += len(line) + 1
    end = start + len(chosen) - 1
    return {"start_line": start, "end_line": end, "text": "\n".join(chosen), "truncated": cut or end < stop}
