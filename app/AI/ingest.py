import csv, hashlib, math, os, re, requests, time
from pathlib import Path
from app.config import CODE_EXTENSIONS, EMBEDDING_MODEL, IGNORE_DIRS, OLLAMA_URL, PRIVACY_EXCLUDE, SCAN_DRIVES, SENSITIVE_FILES, SKIP_EXTENSIONS, SYSTEM_EXCLUDE, TESSRACT_PATH, VECTOR_DIR
from pypdf import PdfReader
from docx import Document as DocxDocument
from psd_tools import PSDImage
from PIL import Image
import pytesseract
import chromadb

try:
    from langdetect import detect as _langdetect_detect, LangDetectException, DetectorFactory
    DetectorFactory.seed = 0
    _HAS_LANGDETECT = True
except ImportError:
    _HAS_LANGDETECT = False

pytesseract.pytesseract.tesseract_cmd = TESSRACT_PATH

client = chromadb.PersistentClient(path=VECTOR_DIR)
collection = client.get_or_create_collection("documents")

MAX_SECTION_CHARS = 4000
EMBED_TIMEOUT = 30
EMBED_MAX_RETRIES = 3
EMBED_BACKOFF_BASE = 1.5
ENTROPY_THRESHOLD = 4.0

SOURCE_TYPE_MAP = {
    **{ext: "code" for ext in CODE_EXTENSIONS},
    "pdf": "document", "docx": "document", "txt": "document", "md": "document",
    "csv": "tabular", "psd": "design",
    "jpg": "image", "jpeg": "image", "png": "image", "bmp": "image", "tiff": "image",
}

BINARY_SIGNATURES = {
    "pdf": (b"%PDF-",), "docx": (b"PK\x03\x04",), "png": (b"\x89PNG\r\n\x1a\n",),
    "jpg": (b"\xff\xd8\xff",), "jpeg": (b"\xff\xd8\xff",), "bmp": (b"BM",),
    "tiff": (b"II*\x00", b"MM\x00*"), "psd": (b"8BPS",),
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


EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[a-zA-Z]{2,}")
PHONE_RE = re.compile(r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b")
SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
CREDIT_CARD_RE = re.compile(r"\b(?:\d[ -]?){13,16}\b")
AWS_KEY_RE = re.compile(r"\bAKIA[0-9A-Z]{16}\b")
HIGH_ENTROPY_TOKEN_RE = re.compile(r"\b[A-Za-z0-9+/_=\-]{20,}\b")


def shannon_entropy(value):
    if not value:
        return 0.0
    counts = {char: value.count(char) for char in set(value)}
    length = len(value)
    return -sum((count / length) * math.log2(count / length) for count in counts.values())


def redact_pii(text):
    hits = {"ssn": 0, "aws_key": 0, "credit_card": 0, "email": 0, "phone": 0, "high_entropy": 0}

    def substitute(pattern, label, value):
        def replace(_match):
            hits[label] += 1
            return f"[REDACTED_{label.upper()}]"
        return pattern.sub(replace, value)

    redacted = text
    for pattern, label in ((SSN_RE, "ssn"), (AWS_KEY_RE, "aws_key"),
                           (CREDIT_CARD_RE, "credit_card"), (EMAIL_RE, "email"),
                           (PHONE_RE, "phone")):
        redacted = substitute(pattern, label, redacted)

    def redact_secret(match):
        if shannon_entropy(match.group(0)) >= ENTROPY_THRESHOLD:
            hits["high_entropy"] += 1
            return "[REDACTED_SECRET]"
        return match.group(0)

    return HIGH_ENTROPY_TOKEN_RE.sub(redact_secret, redacted), hits


def classify_sensitivity(hits):
    if hits.get("ssn") or hits.get("credit_card") or hits.get("aws_key"):
        return "high"
    if hits.get("email") or hits.get("phone") or hits.get("high_entropy"):
        return "medium"
    return "low"


_TOKEN_RE = re.compile(r"\S+")


def count_tokens(text):
    return len(_TOKEN_RE.findall(text))


def detect_language(text, file_type):
    if file_type in CODE_EXTENSIONS:
        return "code"
    if not _HAS_LANGDETECT or len(text[:1000].strip()) < 20:
        return "unknown"
    try:
        return _langdetect_detect(text[:1000].strip())
    except LangDetectException:
        return "unknown"


def read_text(filepath):
    """Extract text from a file based on its extension.
    Supports: pdf, docx, txt, md, csv.
    Returns None for unsupported types.
    """
    ext = filepath.lower().rsplit(".", 1)[-1]

    if ext == "pdf":
        reader = PdfReader(filepath)
        return "\n".join(page.extract_text() or "" for page in reader.pages)

    if ext == "docx":
        doc = DocxDocument(filepath)
        return "\n".join(p.text for p in doc.paragraphs)

    if ext in ("txt", "md"):
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()

    if ext == "csv":
        with open(filepath, newline="", encoding="utf-8", errors="ignore") as f:
            return "\n".join(", ".join(row) for row in csv.reader(f))
        
    if ext in CODE_EXTENSIONS:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
        
    if ext == "psd":
        psd = PSDImage.open(filepath)
        parts = [layer.name for layer in psd if layer.name]
        for layer in psd:
            if layer.kind == 'type':
                parts.append(layer.text)
        return "\n".join(parts)

    if ext in ("jpg", "jpeg", "png", "bmp", "tiff"):
        return pytesseract.image_to_string(Image.open(filepath))
    return None 
    
def is_excluded_path(path):
    """True if path falls under any current exclusion rule (system/privacy/ignored dir/skip extension)
    or outside the configured scan roots. Used to prune stale index entries left over from a
    previous, broader SCAN_DRIVES/IGNORE_DIRS configuration.
    """
    norm = os.path.abspath(path).replace("\\", "/")

    roots = [os.path.abspath(root).replace("\\", "/").rstrip("/") for root in SCAN_DRIVES]
    if not any(norm == root or norm.startswith(root + "/") for root in roots):
        return True
    excludes = [os.path.abspath(ex).replace("\\", "/").rstrip("/") for ex in SYSTEM_EXCLUDE]
    if any(norm == ex or norm.startswith(ex + "/") for ex in excludes):
        return True
    if any(priv in norm for priv in PRIVACY_EXCLUDE):
        return True
    if any(part in IGNORE_DIRS for part in norm.split("/")):
        return True
    if norm.rsplit(".", 1)[-1].lower() in SKIP_EXTENSIONS:
        return True
    return False

def prune_stale(progress_every=2000):
    """Remove index entries whose source file no longer exists or no longer
    satisfies the current scan/exclusion rules (e.g. it moved out of SCAN_DRIVES,
    or a directory it lives under was added to IGNORE_DIRS/PRIVACY_EXCLUDE since
    it was indexed).
    """
    checked, removed = set(), 0
    for meta in collection.get(include=["metadatas"])["metadatas"]:
        source = meta["source"]
        if source in checked:
            continue
        checked.add(source)
        if len(checked) % progress_every == 0:
            print(f"...checked {len(checked)} sources, removed {removed} so far")
        if not os.path.exists(source) or is_excluded_path(source):
            collection.delete(where={"source": source})
            removed += 1
    print(f"Pruned {removed} stale/excluded sources out of {len(checked)} checked")
    return removed

def walk_data_dir(scan_drives):
    for drive in scan_drives:
        for dirpath, dirnames, filenames in os.walk(drive):
            norm = os.path.abspath(dirpath).replace("\\", "/")

            if any(norm.startswith(ex) for ex in SYSTEM_EXCLUDE):
                dirnames[:] = []
                continue
            if any(priv in norm for priv in PRIVACY_EXCLUDE):
                dirnames[:] = []
                continue

            dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS]
            for name in filenames:
                if name in SENSITIVE_FILES:
                    continue
                yield os.path.join(dirpath, name)

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
    header_re = re.compile(r"^\s*(?:[*#_]+\s*)?([A-Z][A-Z \-&]{2,40})\s*(?:[*#_]+\s*)?$", re.MULTILINE)

    sections, last_end, last_header = [], 0, "GENERAL"
    for match in header_re.finditer(text):
        if match.start() > last_end:
            sections.append((last_header, text[last_end:match.start()].strip()))
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
        chunks.append({
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
        })
    return chunks


def store_chunks(chunks, mtime, content_hash):
    """Redact, embed, and persist chunks with their metadata envelope."""
    batch_size = 500
    for start in range(0, len(chunks), batch_size):
        batch = chunks[start:start + batch_size]
        redacted_texts = []
        for chunk in batch:
            redacted_text, hits = redact_pii(chunk["text"])
            chunk["sensitivity"] = classify_sensitivity(hits)
            redacted_texts.append(redacted_text)
        vectors = embed_batch(redacted_texts)
        collection.add(
            ids=[chunk["chunk_id"] for chunk in batch],
            documents=redacted_texts,
            embeddings=vectors,
            metadatas=[
                {
                    "document_id": chunk["document_id"],
                    "section": chunk["section"],
                    "heading_path": chunk["heading_path"],
                    "chunk_index": chunk["chunk_index"],
                    "total_chunks": chunk["total_chunks"],
                    "source": chunk["source"],
                    "file_type": chunk["file_type"],
                    "source_type": chunk["source_type"],
                    "language": chunk["language"],
                    "sensitivity": chunk["sensitivity"],
                    "token_count": chunk["token_count"],
                    "mtime": mtime,
                    "file_hash": content_hash,
                }
                for chunk in batch
            ],
        )


def replace_source_chunks(source, chunks, mtime, content_hash):
    """Replace a source and restore its previous records if indexing fails."""
    existing = collection.get(where={"source": source}, include=["documents", "metadatas", "embeddings"])
    backup = {key: existing.get(key, []) for key in ("ids", "documents", "metadatas", "embeddings")}
    try:
        collection.delete(where={"source": source})
        store_chunks(chunks, mtime, content_hash)
    except Exception:
        collection.delete(where={"source": source})
        if backup["ids"]:
            collection.add(ids=backup["ids"], documents=backup["documents"],
                          embeddings=backup["embeddings"], metadatas=backup["metadatas"])
        raise

def embed(text):
    last_exc = None
    for attempt in range(1, EMBED_MAX_RETRIES + 1):
        try:
            resp = requests.post(f"{OLLAMA_URL}/api/embeddings",
                                 json={"model": EMBEDDING_MODEL, "prompt": text},
                                 timeout=EMBED_TIMEOUT)
            resp.raise_for_status()
            return resp.json()["embedding"]
        except (requests.exceptions.RequestException, KeyError) as exc:
            last_exc = exc
            if attempt < EMBED_MAX_RETRIES:
                time.sleep(EMBED_BACKOFF_BASE ** attempt)
    raise RuntimeError(f"embed() failed after {EMBED_MAX_RETRIES} attempts") from last_exc

def embed_batch(texts):
    last_exc = None
    for attempt in range(1, EMBED_MAX_RETRIES + 1):
        try:
            resp = requests.post(f"{OLLAMA_URL}/api/embed",
                                 json={"model": EMBEDDING_MODEL, "input": texts},
                                 timeout=EMBED_TIMEOUT)
            resp.raise_for_status()
            return resp.json()["embeddings"]
        except (requests.exceptions.RequestException, KeyError) as exc:
            last_exc = exc
            if attempt < EMBED_MAX_RETRIES:
                time.sleep(EMBED_BACKOFF_BASE ** attempt)
    raise RuntimeError(f"embed_batch() failed after {EMBED_MAX_RETRIES} attempts") from last_exc

def file_hash(filepath, chunk_size=1024 * 1024):
    """Return the SHA-256 digest of a file without loading it all into memory."""
    digest = hashlib.sha256()
    with open(filepath, "rb") as file:
        for chunk in iter(lambda: file.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def search(query_text, n_results=5, source_type=None, file_type=None, sensitivity=None):
    """Search the index with optional metadata filters."""
    conditions = []
    for key, value in (("source_type", source_type), ("file_type", file_type),
                       ("sensitivity", sensitivity)):
        if value:
            conditions.append({key: value})
    where = {"$and": conditions} if len(conditions) > 1 else (conditions[0] if conditions else None)
    return collection.query(query_embeddings=[embed(query_text)], n_results=n_results, where=where)

def ingest_all(max_size_mb=25, progress_every=500):
    doc_id, indexed, skipped, unchanged, scanned = 0, 0, 0, 0, 0
    start_time = time.time()
    for path in walk_data_dir(SCAN_DRIVES):
        scanned += 1
        if scanned % progress_every == 0:
            elapsed = time.time() - start_time
            rate = scanned / elapsed
            print(f"...scanned {scanned} files in {elapsed:.0f}s ({rate:.1f} files/s) "
                  f"- indexed {indexed}, unchanged {unchanged}, skipped {skipped}")

        if path.lower().rsplit(".", 1)[-1] in SKIP_EXTENSIONS:
            skipped += 1
            continue

        source = os.path.abspath(path)
        try:
            ext = Path(source).suffix.lower().lstrip(".") or "unknown"
            file_size = os.path.getsize(path)
            if file_size > max_size_mb * 1024 * 1024:
                print(f"Skipped {path}: file too large (>{max_size_mb}MB)")
                skipped += 1
                continue

            sniffed_kind, is_safe = sniff_mime(path, ext)
            if not is_safe:
                print(f"Skipped {path}: MIME pre-check failed (sniffed as '{sniffed_kind}', declared .{ext})")
                skipped += 1
                continue

            content_hash = file_hash(path)
            existing = collection.get(where={"source": source}, limit=1, include=["metadatas"])
            if (existing["metadatas"]
                    and existing["metadatas"][0].get("file_hash") == content_hash):
                unchanged += 1
                continue

            print(f"Processing: {path}")
            mtime = os.path.getmtime(path)
            text = read_text(path)
            if text:
                text = text.encode("utf-8", "ignore").decode("utf-8")
        except Exception as e:
            print(f"Skipped {path}: {e}")
            skipped += 1
            continue

        if not text or not text.strip():
            print("  -> skipped (empty)")
            skipped += 1
            continue

        file_type = Path(source).suffix.lower().lstrip(".") or "unknown"
        source_type = get_source_type(file_type)
        chunks = chunk_by_section(text, make_document_id(content_hash), source, file_type, source_type)

        replace_source_chunks(source, chunks, mtime, content_hash)
        doc_id += len(chunks)
        indexed += 1
        print(f"  -> indexed ({len(chunks)} chunks)")

    elapsed = time.time() - start_time
    print(f"Indexed {indexed} files ({doc_id} chunks), skipped {skipped} unsupported/empty/oversized files, "
          f"{unchanged} unchanged, {scanned} scanned total in {elapsed:.0f}s")
    
def reset_index():
    """Delete all documents from the index."""
    collection.delete(where={})
    print("Index reset complete.")

if __name__ == "__main__":
    import sys
    if "--prune-only" in sys.argv:
        prune_stale()
    elif "--search" in sys.argv:
        idx = sys.argv.index("--search")
        query_text = sys.argv[idx + 1]
        source_type_filter = None
        if "--source-type" in sys.argv:
            source_type_filter = sys.argv[sys.argv.index("--source-type") + 1]
        results = search(query_text, source_type=source_type_filter)
        for document, metadata in zip(results["documents"][0], results["metadatas"][0]):
            print(f"[{metadata.get('source_type')}] {metadata.get('source')} :: {metadata.get('heading_path')}")
            print(document[:200])
            print("---")
    else:
        ingest_all()
        prune_stale()