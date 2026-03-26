"""
Cadence Knowledge Base Ingestion Script
========================================
Reads documents from raw-docs/, chunks them, creates embeddings
using sentence-transformers, and stores in ChromaDB.

Usage:
    python ingest.py

Re-run whenever you add new documents to raw-docs/.
"""

import os
from pathlib import Path

import chromadb
from chromadb.utils import embedding_functions

# Optional document parsers
try:
    from PyPDF2 import PdfReader
except ImportError:
    PdfReader = None
    print("Warning: PyPDF2 not installed — PDF files will be skipped")

try:
    import docx
except ImportError:
    docx = None
    print("Warning: python-docx not installed — DOCX files will be skipped")

# ── Paths ──────────────────────────────────────────────
BASE_DIR = Path(__file__).parent.absolute()
RAW_DOCS_DIR = BASE_DIR / "raw-docs"
EMBEDDINGS_DIR = BASE_DIR / "embeddings"

# Create dirs if missing
RAW_DOCS_DIR.mkdir(parents=True, exist_ok=True)
EMBEDDINGS_DIR.mkdir(parents=True, exist_ok=True)

# ── ChromaDB Setup ─────────────────────────────────────
client = chromadb.PersistentClient(path=str(EMBEDDINGS_DIR))

embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
    model_name="all-MiniLM-L6-v2"
)

collection = client.get_or_create_collection(
    name="cadence_knowledge_base",
    embedding_function=embedding_fn,
    metadata={"description": "Cadence brand documents and knowledge"}
)

# ── Text Extraction ────────────────────────────────────
def extract_text(filepath: Path) -> str:
    """Extract text from PDF, DOCX, TXT, MD, or CSV files."""
    ext = filepath.suffix.lower()
    try:
        if ext == ".pdf":
            if PdfReader is None:
                print(f"  ⚠ Skipping {filepath.name} (PyPDF2 not installed)")
                return ""
            reader = PdfReader(filepath)
            return "\n".join(page.extract_text() or "" for page in reader.pages)

        elif ext == ".docx":
            if docx is None:
                print(f"  ⚠ Skipping {filepath.name} (python-docx not installed)")
                return ""
            doc = docx.Document(filepath)
            return "\n".join(p.text for p in doc.paragraphs)

        elif ext in (".txt", ".md", ".csv"):
            return filepath.read_text(encoding="utf-8")

        else:
            print(f"  ⚠ Unsupported format: {ext}")
            return ""

    except Exception as e:
        print(f"  ✗ Error reading {filepath.name}: {e}")
        return ""

# ── Chunking ───────────────────────────────────────────
def chunk_text(text: str, chunk_size: int = 500, overlap: int = 50) -> list[str]:
    """Split text into chunks by paragraph boundaries."""
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks = []
    current = ""

    for para in paragraphs:
        if len(current) + len(para) < chunk_size:
            current += para + "\n\n"
        else:
            if current:
                chunks.append(current.strip())
            current = para + "\n\n"

    if current.strip():
        chunks.append(current.strip())

    # Break overly large chunks
    final = []
    for chunk in chunks:
        if len(chunk) > chunk_size * 1.5:
            for i in range(0, len(chunk), chunk_size - overlap):
                sub = chunk[i : i + chunk_size]
                if sub.strip():
                    final.append(sub.strip())
        else:
            final.append(chunk)

    return final

# ── Main ───────────────────────────────────────────────
def main():
    print("=" * 50)
    print("  Cadence Knowledge Base — Ingestion")
    print("=" * 50)

    files = []
    for ext in ("*.txt", "*.md", "*.pdf", "*.docx", "*.csv"):
        files.extend(RAW_DOCS_DIR.glob(ext))

    if not files:
        print(f"\nNo documents found in {RAW_DOCS_DIR}")
        print("Add your brand docs, PDFs, and SOPs there, then re-run.")
        return

    total = 0

    for fp in files:
        print(f"\n📄 {fp.name}")

        # Remove old chunks for this file (allows re-ingestion)
        existing = collection.get(where={"source": fp.name})
        if existing and existing["ids"]:
            collection.delete(ids=existing["ids"])
            print(f"  ↻ Removed {len(existing['ids'])} old chunks")

        text = extract_text(fp)
        if not text.strip():
            print("  ⚠ No text extracted — skipping")
            continue

        chunks = chunk_text(text)
        print(f"  → {len(chunks)} chunks generated")

        ids = [f"{fp.name}_chunk_{i}" for i in range(len(chunks))]
        metadatas = [{"source": fp.name, "chunk_index": i} for i in range(len(chunks))]

        collection.add(documents=chunks, metadatas=metadatas, ids=ids)
        total += len(chunks)
        print(f"  ✓ Indexed successfully")

    print("\n" + "=" * 50)
    print(f"  Done! {total} chunks indexed from {len(files)} file(s)")
    print(f"  Vector store: {EMBEDDINGS_DIR}")
    print("=" * 50)


if __name__ == "__main__":
    main()
