"""
Cadence Brain — Custom MCP Server
===================================
A FastMCP server that exposes brand knowledge AND Google Sheets tools to Claude Desktop.

Tools available:
  RAG & Knowledge:
  - search_knowledge_base(query)  → semantic search across all brand docs
  - list_documents()              → list all indexed documents
  - add_note(title, content)      → save a note/analysis to outputs/
  - get_brand_context(topic)      → quick-access brand info by topic

  Google Sheets:
  - read_sheet(spreadsheet_id, tab_name)  → read data from a Google Sheet tab
  - write_sheet(spreadsheet_id, tab_name, row_data)  → append a row
  - list_sheet_tabs(spreadsheet_id)  → list all tabs in a spreadsheet

Run with:
    python cadence_brain_server.py

Add to claude_desktop_config.json:
    {
      "mcpServers": {
        "cadence-brain": {
          "command": "python",
          "args": ["D:\\\\AI\\\\Anti\\\\cadence-brain\\\\cadence_brain_server.py"]
        }
      }
    }
"""

import os
import json
import datetime
from pathlib import Path

from fastmcp import FastMCP
import chromadb
from chromadb.utils import embedding_functions

# Google Sheets
try:
    import gspread
    from google.oauth2.service_account import Credentials
    SHEETS_AVAILABLE = True
except ImportError:
    SHEETS_AVAILABLE = False
    print("Warning: gspread not installed — Google Sheets tools disabled")

# ── Paths ──────────────────────────────────────────────
BASE_DIR = Path(__file__).parent.absolute()
RAW_DOCS_DIR = BASE_DIR / "raw-docs"
EMBEDDINGS_DIR = BASE_DIR / "embeddings"
OUTPUTS_DIR = BASE_DIR / "outputs"

# Ensure directories exist
for d in (RAW_DOCS_DIR, EMBEDDINGS_DIR, OUTPUTS_DIR):
    d.mkdir(parents=True, exist_ok=True)

CREDENTIALS_FILE = BASE_DIR / "credentials.json"

# ── Google Sheets Setup ────────────────────────────────
def get_sheets_client():
    """Get authenticated Google Sheets client."""
    if not SHEETS_AVAILABLE:
        return None
    if not CREDENTIALS_FILE.exists():
        return None
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive.readonly",
    ]
    creds = Credentials.from_service_account_file(str(CREDENTIALS_FILE), scopes=scopes)
    return gspread.authorize(creds)

# ── ChromaDB Setup ─────────────────────────────────────
chroma_client = chromadb.PersistentClient(path=str(EMBEDDINGS_DIR))
embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
    model_name="all-MiniLM-L6-v2"
)

# Import ingestion helpers from ingest.py
import sys
sys.path.insert(0, str(BASE_DIR))
from ingest import extract_text, chunk_text

# File watcher imports
import threading
import time
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler


def get_collection():
    """Get or create the knowledge base collection."""
    return chroma_client.get_or_create_collection(
        name="cadence_knowledge_base",
        embedding_function=embedding_fn,
        metadata={"description": "Cadence brand documents and knowledge"}
    )


def _ingest_single_file(filepath: Path) -> str:
    """Ingest a single file into the knowledge base. Returns status message."""
    collection = get_collection()

    # Remove old chunks for this file if they exist
    existing = collection.get(where={"source": filepath.name})
    if existing and existing["ids"]:
        collection.delete(ids=existing["ids"])

    text = extract_text(filepath)
    if not text.strip():
        return f"⚠ {filepath.name} — no text extracted"

    chunks = chunk_text(text)
    ids = [f"{filepath.name}_chunk_{i}" for i in range(len(chunks))]
    metadatas = [{"source": filepath.name, "chunk_index": i} for i in range(len(chunks))]
    collection.add(documents=chunks, metadatas=metadatas, ids=ids)
    return f"✅ {filepath.name} — {len(chunks)} chunks indexed"


# ── Background File Watcher ───────────────────────────
SUPPORTED_EXTENSIONS = {".txt", ".md", ".pdf", ".docx", ".csv"}


class DocHandler(FileSystemEventHandler):
    """Watches raw-docs/ and auto-indexes new or modified files."""

    def _should_process(self, path):
        return Path(path).suffix.lower() in SUPPORTED_EXTENSIONS

    def on_created(self, event):
        if not event.is_directory and self._should_process(event.src_path):
            # Small delay to ensure file is fully written
            time.sleep(1)
            fp = Path(event.src_path)
            print(f"[INGEST] Auto-ingesting new file: {fp.name}", file=sys.stderr)
            result = _ingest_single_file(fp)
            print(f"  {result}", file=sys.stderr)

    def on_modified(self, event):
        if not event.is_directory and self._should_process(event.src_path):
            time.sleep(1)
            fp = Path(event.src_path)
            print(f"[INGEST] Auto-re-indexing modified file: {fp.name}", file=sys.stderr)
            result = _ingest_single_file(fp)
            print(f"  {result}", file=sys.stderr)


def _start_file_watcher():
    """Start background thread monitoring raw-docs/ for changes."""
    observer = Observer()
    observer.schedule(DocHandler(), str(RAW_DOCS_DIR), recursive=False)
    observer.daemon = True
    observer.start()
    print(f"[WATCHER] File watcher active - monitoring {RAW_DOCS_DIR}", file=sys.stderr)


# Start the watcher immediately
_start_file_watcher()


# ── MCP Server ─────────────────────────────────────────
mcp = FastMCP(
    "Cadence Brain",
    instructions=(
        "Brand intelligence server for Cadence — a mid-premium nutritional "
        "supplements brand. Provides semantic search across brand documents, "
        "product briefs, SOPs, and strategy docs."
    ),
)


@mcp.tool()
def search_knowledge_base(query: str, top_k: int = 5) -> str:
    """
    Semantic search across all Cadence brand documents.

    Use this to find relevant information from the brand book, product briefs,
    SOPs, competitor research, and strategy docs.

    Args:
        query: What you want to find (e.g. "REST line pricing strategy",
               "brand voice guidelines", "magnesium product positioning")
        top_k: Number of results to return (default 5, max 10)
    """
    top_k = min(top_k, 10)
    collection = get_collection()

    if collection.count() == 0:
        return (
            "⚠ Knowledge base is empty. No documents have been ingested yet.\n"
            "Run 'python ingest.py' to index documents from the raw-docs/ folder."
        )

    results = collection.query(query_texts=[query], n_results=top_k)

    if not results["documents"][0]:
        return f"No results found for: '{query}'"

    output_lines = [f"🔍 Search results for: '{query}'\n"]

    for i, (doc, meta, dist) in enumerate(
        zip(
            results["documents"][0],
            results["metadatas"][0],
            results["distances"][0],
        )
    ):
        source = meta.get("source", "Unknown")
        relevance = max(0, round((1 - dist / 2) * 100, 1))
        output_lines.append(
            f"--- Result {i + 1} (Source: {source}, Relevance: {relevance}%) ---\n"
            f"{doc}\n"
        )

    return "\n".join(output_lines)


@mcp.tool()
def list_documents() -> str:
    """
    List all documents currently indexed in the Cadence knowledge base.

    Returns a summary of each document including its name and number of
    indexed chunks.
    """
    collection = get_collection()

    if collection.count() == 0:
        return (
            "Knowledge base is empty.\n"
            "Add documents to raw-docs/ and run 'python ingest.py'."
        )

    # Get all metadata to count chunks per document
    all_data = collection.get()
    doc_chunks: dict[str, int] = {}

    for meta in all_data["metadatas"]:
        source = meta.get("source", "Unknown")
        doc_chunks[source] = doc_chunks.get(source, 0) + 1

    lines = [
        f"📚 Cadence Knowledge Base — {collection.count()} total chunks\n",
        f"{'Document':<40} {'Chunks':>6}",
        "-" * 48,
    ]

    for name, count in sorted(doc_chunks.items()):
        lines.append(f"{name:<40} {count:>6}")

    # Also list any files in raw-docs that aren't indexed yet
    indexed_names = set(doc_chunks.keys())
    raw_files = set()
    for ext in ("*.txt", "*.md", "*.pdf", "*.docx", "*.csv"):
        raw_files.update(f.name for f in RAW_DOCS_DIR.glob(ext))

    unindexed = raw_files - indexed_names
    if unindexed:
        lines.append(f"\n⚠ {len(unindexed)} file(s) in raw-docs/ not yet indexed:")
        for name in sorted(unindexed):
            lines.append(f"  - {name}")
        lines.append("Run 'python ingest.py' to index them.")

    return "\n".join(lines)


@mcp.tool()
def add_note(title: str, content: str) -> str:
    """
    Save a strategy note, analysis, or response to the outputs folder.

    Use this to persist Claude's analysis, recommendations, campaign briefs,
    or any generated content for later reference.

    Args:
        title: Short title for the note (used as filename)
        content: The full content to save
    """
    # Sanitize title for filename
    safe_title = "".join(c if c.isalnum() or c in " -_" else "_" for c in title)
    safe_title = safe_title.strip().replace(" ", "_")
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{timestamp}_{safe_title}.md"

    filepath = OUTPUTS_DIR / filename
    filepath.write_text(
        f"# {title}\n\n"
        f"*Generated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*\n\n"
        f"{content}\n",
        encoding="utf-8",
    )

    return f"✅ Note saved: {filepath.name}\nPath: {filepath}"


@mcp.tool()
def get_brand_context(topic: str) -> str:
    """
    Get pre-structured brand context for common Cadence topics.

    This combines a focused knowledge base search with structured
    product line information. Useful for quickly grounding responses
    in Cadence's brand identity.

    Args:
        topic: One of: "pricing", "positioning", "products", "competitors",
               "brand_voice", "daily_line", "form_line", "rest_line",
               or any free-text topic
    """
    # Static brand reference
    brand_info = {
        "products": (
            "Cadence Product Lines:\n"
            "• DAILY (daily essentials): Base, Core, Flora, Guard\n"
            "• FORM (performance): Drive, Peak, Build, Flow\n"
            "• REST (recovery & sleep): Ease, Drift, Calm, Mend\n"
            "Target: Indian professionals aged 22-35\n"
            "Positioning: Mid-premium nutritional supplements"
        ),
        "daily_line": "DAILY line: Base, Core, Flora, Guard — everyday essentials for foundational health",
        "form_line": "FORM line: Drive, Peak, Build, Flow — performance and fitness optimization",
        "rest_line": "REST line: Ease, Drift, Calm, Mend — recovery, sleep, and stress management",
        "brand_voice": (
            "Cadence brand voice: Confident but not aggressive. Scientific but accessible. "
            "Premium but not elitist. Speaks to ambitious young professionals who see "
            "health as infrastructure for performance."
        ),
    }

    lines = []

    # Add static info if we have it
    topic_lower = topic.lower().replace(" ", "_")
    if topic_lower in brand_info:
        lines.append(f"📋 Brand Reference — {topic}\n")
        lines.append(brand_info[topic_lower])
        lines.append("")

    # Always supplement with a knowledge base search
    collection = get_collection()
    if collection.count() > 0:
        results = collection.query(query_texts=[topic], n_results=3)
        if results["documents"][0]:
            lines.append(f"📄 Related knowledge base excerpts:\n")
            for i, (doc, meta) in enumerate(
                zip(results["documents"][0], results["metadatas"][0])
            ):
                source = meta.get("source", "Unknown")
                lines.append(f"[{source}]: {doc[:300]}{'...' if len(doc) > 300 else ''}\n")
    else:
        lines.append(
            "\n⚠ Knowledge base is empty — run 'python ingest.py' to index brand docs."
        )

    return "\n".join(lines) if lines else f"No brand context found for topic: '{topic}'"


@mcp.tool()
def list_output_notes() -> str:
    """
    List all saved notes and analyses in the outputs folder.

    Shows previously saved strategy notes, campaign briefs, and
    AI-generated analyses.
    """
    files = sorted(OUTPUTS_DIR.glob("*.md"))
    if not files:
        return "No output notes found. Use add_note() to save analyses."

    lines = ["📝 Saved Notes & Analyses\n"]
    for f in files:
        size_kb = f.stat().st_size / 1024
        lines.append(f"  • {f.name} ({size_kb:.1f} KB)")

    return "\n".join(lines)


@mcp.tool()
def read_output_note(filename: str) -> str:
    """
    Read a previously saved note from the outputs folder.

    Args:
        filename: The filename to read (from list_output_notes)
    """
    filepath = OUTPUTS_DIR / filename
    if not filepath.exists():
        return f"File not found: {filename}. Use list_output_notes() to see available files."
    if not filepath.suffix == ".md":
        return "Only .md files can be read."

    return filepath.read_text(encoding="utf-8")


@mcp.tool()
def ingest_new_documents() -> str:
    """
    Index any new or updated documents from the raw-docs folder.

    Scans raw-docs/ for files not yet in the knowledge base and indexes them.
    Also re-indexes files that have been updated. Call this after adding
    new documents to raw-docs/.
    """
    collection = get_collection()

    files = []
    for ext in ("*.txt", "*.md", "*.pdf", "*.docx", "*.csv"):
        files.extend(RAW_DOCS_DIR.glob(ext))

    if not files:
        return "No documents found in raw-docs/. Add files there first."

    # Find which files are already indexed
    indexed_sources = set()
    if collection.count() > 0:
        all_meta = collection.get()
        for meta in all_meta["metadatas"]:
            indexed_sources.add(meta.get("source", ""))

    new_files = [f for f in files if f.name not in indexed_sources]

    if not new_files:
        return f"✅ All {len(files)} documents are already indexed. No new files to process."

    total = 0
    results = []

    for fp in new_files:
        text = extract_text(fp)
        if not text.strip():
            results.append(f"⚠ {fp.name} — no text extracted, skipped")
            continue

        chunks = chunk_text(text)
        ids = [f"{fp.name}_chunk_{i}" for i in range(len(chunks))]
        metadatas = [{"source": fp.name, "chunk_index": i} for i in range(len(chunks))]

        collection.add(documents=chunks, metadatas=metadatas, ids=ids)
        total += len(chunks)
        results.append(f"✅ {fp.name} — {len(chunks)} chunks indexed")

    lines = [f"📥 Ingestion complete — {total} new chunks from {len(new_files)} file(s)\n"]
    lines.extend(results)
    return "\n".join(lines)


@mcp.tool()
def remove_document(filename: str, delete_file: bool = True) -> str:
    """
    Remove a document from the knowledge base and optionally delete the source file.

    This cleanly removes all embeddings/chunks for the specified document
    from ChromaDB, leaving no leftovers.

    Args:
        filename: Name of the document to remove (e.g. "brand_book.pdf").
                  Use list_documents() to see indexed files.
        delete_file: If True (default), also delete the file from raw-docs/
    """
    collection = get_collection()

    # Remove embeddings
    existing = collection.get(where={"source": filename})
    removed_chunks = 0
    if existing and existing["ids"]:
        removed_chunks = len(existing["ids"])
        collection.delete(ids=existing["ids"])

    # Remove file
    file_deleted = False
    if delete_file:
        filepath = RAW_DOCS_DIR / filename
        if filepath.exists():
            filepath.unlink()
            file_deleted = True

    lines = []
    if removed_chunks > 0:
        lines.append(f"✅ Removed {removed_chunks} chunks for '{filename}' from knowledge base")
    else:
        lines.append(f"⚠ No embeddings found for '{filename}'")

    if file_deleted:
        lines.append(f"🗑 Deleted file from raw-docs/")
    elif delete_file:
        lines.append(f"⚠ File '{filename}' not found in raw-docs/ (embeddings still removed)")

    return "\n".join(lines)


# ── Google Sheets Tools ────────────────────────────────

def _find_spreadsheet(gc, name_or_id: str):
    """Find a spreadsheet by name or ID."""
    # First try as an ID (looks like a long alphanumeric string)
    if len(name_or_id) > 20 and " " not in name_or_id:
        try:
            return gc.open_by_key(name_or_id)
        except Exception:
            pass
    # Then try by name
    try:
        return gc.open(name_or_id)
    except gspread.exceptions.SpreadsheetNotFound:
        return None


@mcp.tool()
def list_all_spreadsheets() -> str:
    """
    List ALL Google Sheets shared with the Cadence service account.

    Use this first to discover available spreadsheets, then use their
    exact name with read_sheet, write_sheet, or list_sheet_tabs.
    """
    gc = get_sheets_client()
    if gc is None:
        return "❌ Google Sheets not available. Check credentials.json."

    try:
        all_sheets = gc.list_spreadsheet_files()
        if not all_sheets:
            return "No spreadsheets found. Share your Google Sheets with: claude@extended-cable-467116-v9.iam.gserviceaccount.com"

        lines = ["📋 Available Spreadsheets\n"]
        for sheet in all_sheets:
            lines.append(f"  • {sheet['name']}")
        lines.append(f"\nTotal: {len(all_sheets)} spreadsheet(s)")
        lines.append("Use read_sheet(spreadsheet_name, tab_name) to read data.")
        return "\n".join(lines)

    except Exception as e:
        return f"❌ Error listing spreadsheets: {e}"


@mcp.tool()
def read_sheet(spreadsheet: str, tab_name: str = "Sheet1") -> str:
    """
    Read all data from a Google Sheets tab.

    Args:
        spreadsheet: Spreadsheet name (e.g. "Cadence Operations") or ID
        tab_name: Tab to read (default: Sheet1).
                  Cadence tabs: Inventory, Content Calendar, Campaign Calendar, Reorder Log
    """
    gc = get_sheets_client()
    if gc is None:
        return "❌ Google Sheets not available. Check credentials.json."

    try:
        ss = _find_spreadsheet(gc, spreadsheet)
        if ss is None:
            return f"❌ Spreadsheet '{spreadsheet}' not found. Use list_all_spreadsheets() to see available sheets."

        worksheet = ss.worksheet(tab_name)
        records = worksheet.get_all_records()

        if not records:
            return f"Tab '{tab_name}' is empty or has no data rows."

        headers = list(records[0].keys())
        lines = [f"📊 {ss.title} → {tab_name} — {len(records)} rows\n"]
        lines.append(" | ".join(headers))
        lines.append("-" * (len(" | ".join(headers))))

        for row in records:
            lines.append(" | ".join(str(row.get(h, "")) for h in headers))

        return "\n".join(lines)

    except gspread.exceptions.WorksheetNotFound:
        return f"❌ Tab '{tab_name}' not found. Use list_sheet_tabs() to see available tabs."
    except Exception as e:
        return f"❌ Error reading sheet: {e}"


@mcp.tool()
def write_sheet(spreadsheet: str, tab_name: str, row_data: str) -> str:
    """
    Append a row of data to a Google Sheets tab.

    Args:
        spreadsheet: Spreadsheet name (e.g. "Cadence Operations") or ID
        tab_name: Tab to write to
        row_data: Comma-separated values for the new row
                  Example: "2026-03-23, REST Ease, Low Stock, Reorder 500 units"
    """
    gc = get_sheets_client()
    if gc is None:
        return "❌ Google Sheets not available. Check credentials.json."

    try:
        ss = _find_spreadsheet(gc, spreadsheet)
        if ss is None:
            return f"❌ Spreadsheet '{spreadsheet}' not found."

        worksheet = ss.worksheet(tab_name)
        values = [v.strip() for v in row_data.split(",")]
        worksheet.append_row(values)
        return f"✅ Row appended to '{ss.title}' → '{tab_name}': {values}"

    except Exception as e:
        return f"❌ Error writing to sheet: {e}"


@mcp.tool()
def list_sheet_tabs(spreadsheet: str) -> str:
    """
    List all tabs/worksheets in a Google Spreadsheet.

    Args:
        spreadsheet: Spreadsheet name (e.g. "Cadence Operations") or ID
    """
    gc = get_sheets_client()
    if gc is None:
        return "❌ Google Sheets not available. Check credentials.json."

    try:
        ss = _find_spreadsheet(gc, spreadsheet)
        if ss is None:
            return f"❌ Spreadsheet '{spreadsheet}' not found."

        tabs = ss.worksheets()
        lines = [f"📋 {ss.title}\n"]
        for tab in tabs:
            lines.append(f"  • {tab.title} ({tab.row_count} rows × {tab.col_count} cols)")
        return "\n".join(lines)

    except Exception as e:
        return f"❌ Error listing tabs: {e}"


# ── Entry Point ────────────────────────────────────────
if __name__ == "__main__":
    mcp.run()
