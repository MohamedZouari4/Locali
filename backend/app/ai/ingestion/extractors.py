"""Turns a file into plain text: checks its magic bytes, then reads PDF, DOCX, CSV, text, code,
PSD layers or (with Tesseract OCR) images. Also tags language and token count.
"""

import csv

import pytesseract
from docx import Document as DocxDocument
from PIL import Image
from psd_tools import PSDImage
from pypdf import PdfReader

from app.core.config import CODE_EXTENSIONS, TESSERACT_PATH

try:
    from langdetect import DetectorFactory, LangDetectException
    from langdetect import detect as _langdetect_detect

    DetectorFactory.seed = 0
    _HAS_LANGDETECT = True
except ImportError:
    _HAS_LANGDETECT = False

pytesseract.pytesseract.tesseract_cmd = TESSERACT_PATH

IMAGE_EXTENSIONS = ("jpg", "jpeg", "png", "bmp", "tiff")

SOURCE_TYPE_MAP = {
    **{ext: "code" for ext in CODE_EXTENSIONS},
    "pdf": "document",
    "docx": "document",
    "txt": "document",
    "md": "document",
    "csv": "tabular",
    "psd": "design",
    **{ext: "image" for ext in IMAGE_EXTENSIONS},
}

BINARY_SIGNATURES = {
    "pdf": (b"%PDF-",),
    "docx": (b"PK\x03\x04",),
    "png": (b"\x89PNG\r\n\x1a\n",),
    "jpg": (b"\xff\xd8\xff",),
    "jpeg": (b"\xff\xd8\xff",),
    "bmp": (b"BM",),
    "tiff": (b"II*\x00", b"MM\x00*"),
    "psd": (b"8BPS",),
}
DANGEROUS_SIGNATURES = ((b"MZ", "pe_executable"), (b"\x7fELF", "elf_executable"))


def get_source_type(file_type):
    return SOURCE_TYPE_MAP.get(file_type, "other")


def sniff_mime(filepath, declared_ext):
    """Reject dangerous binaries and mislabeled binary files before parsing."""
    with open(filepath, "rb") as file:
        head = file.read(32)
    for magic, kind in DANGEROUS_SIGNATURES:
        if head.startswith(magic):
            return kind, False
    expected = BINARY_SIGNATURES.get(declared_ext)
    if expected is not None:
        return (declared_ext, True) if any(head.startswith(sig) for sig in expected) else ("mismatched_binary", False)
    return ("binary", False) if b"\x00" in head else ("text", True)


def read_text(filepath):
    """Extract text from a file based on its extension. Returns None for unsupported types."""
    ext = filepath.lower().rsplit(".", 1)[-1]

    if ext == "pdf":
        reader = PdfReader(filepath)
        return "\n".join(page.extract_text() or "" for page in reader.pages)

    if ext == "docx":
        doc = DocxDocument(filepath)
        return "\n".join(p.text for p in doc.paragraphs)

    if ext == "csv":
        with open(filepath, newline="", encoding="utf-8", errors="ignore") as f:
            return "\n".join(", ".join(row) for row in csv.reader(f))

    if ext in CODE_EXTENSIONS:  # includes txt and md
        with open(filepath, encoding="utf-8", errors="ignore") as f:
            return f.read()

    if ext == "psd":
        psd = PSDImage.open(filepath)
        parts = [layer.name for layer in psd if layer.name]
        for layer in psd:
            if layer.kind == "type":
                parts.append(layer.text)
        return "\n".join(parts)

    if ext in IMAGE_EXTENSIONS:
        return pytesseract.image_to_string(Image.open(filepath))
    return None


def count_tokens(text):
    # Whitespace-separated words: a cheap, model-independent size estimate.
    return len(text.split())


def detect_language(text, file_type):
    if file_type in CODE_EXTENSIONS:
        return "code"
    if not _HAS_LANGDETECT or len(text[:1000].strip()) < 20:
        return "unknown"
    try:
        return _langdetect_detect(text[:1000].strip())
    except LangDetectException:
        return "unknown"
