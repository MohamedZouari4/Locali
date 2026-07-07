import os, csv, requests, time
from config import CODE_EXTENSIONS, EMBEDDING_MODEL, IGNORE_DIRS, OLLAMA_URL, PRIVACY_EXCLUDE, SCAN_DRIVES, SENSITIVE_FILES, SKIP_EXTENSIONS, SYSTEM_EXCLUDE, TESSRACT_PATH, VECTOR_DIR
from pypdf import PdfReader
from docx import Document as DocxDocument
from psd_tools import PSDImage
from PIL import Image
import pytesseract
import chromadb

pytesseract.pytesseract.tesseract_cmd = TESSRACT_PATH

client = chromadb.PersistentClient(path=VECTOR_DIR)
collection = client.get_or_create_collection("documents")


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

    if not any(norm.startswith(os.path.abspath(root).replace("\\", "/")) for root in SCAN_DRIVES):
        return True
    if any(norm.startswith(ex) for ex in SYSTEM_EXCLUDE):
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
    total = collection.count()
    checked, removed = set(), 0
    for offset in range(0, total, 1000):
        batch = collection.get(limit=1000, offset=offset, include=["metadatas"])
        for meta in batch["metadatas"]:
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

def chunk_text(text, size=800, overlap=100):
    chunks, start = [], 0
    while start < len(text):
        chunks.append(text[start:start + size])
        start += size - overlap
    return chunks

def embed(text):
    resp = requests.post(f"{OLLAMA_URL}/api/embeddings",
                          json={"model": EMBEDDING_MODEL, "prompt": text})
    resp.raise_for_status()
    return resp.json()["embedding"]

def embed_batch(texts):
    resp = requests.post(f"{OLLAMA_URL}/api/embed",
                          json={"model": EMBEDDING_MODEL, "input": texts})
    resp.raise_for_status()
    return resp.json()["embeddings"]

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
            mtime = os.path.getmtime(path)
            if os.path.getsize(path) > max_size_mb * 1024 * 1024:
                print(f"Skipped {path}: file too large (>{max_size_mb}MB)")
                skipped += 1
                continue

            existing = collection.get(where={"source": source}, limit=1, include=["metadatas"])
            if existing["metadatas"] and existing["metadatas"][0].get("mtime") == mtime:
                unchanged += 1
                continue

            print(f"Processing: {path}")
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

        chunks = chunk_text(text)

        collection.delete(where={"source": source})
        batch_size = 500
        for start in range(0, len(chunks), batch_size):
            batch = chunks[start:start + batch_size]
            vectors = embed_batch(batch)
            collection.add(
                ids=[f"{source}::{start + i}" for i in range(len(batch))],
                documents=batch,
                embeddings=vectors,
                metadatas=[{"source": source, "mtime": mtime} for _ in batch],
            )
        doc_id += len(chunks)
        indexed += 1
        print(f"  -> indexed ({len(chunks)} chunks)")

    elapsed = time.time() - start_time
    print(f"Indexed {indexed} files ({doc_id} chunks), skipped {skipped} unsupported/empty/oversized files, "
          f"{unchanged} unchanged, {scanned} scanned total in {elapsed:.0f}s")

if __name__ == "__main__":
    import sys
    if "--prune-only" in sys.argv:
        prune_stale()
    else:
        ingest_all()
        prune_stale()