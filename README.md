CADENCE INTELLIGENCE INFRASTRUCTURE
AI Architect Simulation - Week 4 Submission
============================================

A custom MCP (Model Context Protocol) server that turns Claude Desktop into a Brand
Intelligence Assistant for Cadence - a mid-premium nutritional supplements brand
targeting Indian professionals.

Instead of Claude being just a chatbot, this build gives it structured access to
Cadence's private brand knowledge and live Google Sheets data, and lets it write
analysis back into a local workspace.


------------------------------------------------------------
1. WHAT PROBLEM THIS SOLVES
------------------------------------------------------------

Running a D2C brand like Cadence means context is fragmented:

- Brand strategy and voice live in long PDFs and internal docs
- Operations live in Google Sheets (inventory, campaigns, content calendars)
- Insights usually depend on someone manually reading both and synthesising them

The result: founders and operators spend time hunting for information instead of
asking a question and getting an answer grounded in real data.

This system solves that by giving Claude Desktop:

- Direct, semantic access to all Cadence brand docs on the local machine
- Read/write access to operational Google Sheets
- A way to save its own analyses back into a structured folder

All from a single conversation, with no manual copy-paste.


------------------------------------------------------------
2. WHAT THIS SYSTEM DOES
------------------------------------------------------------

Claude Desktop connects to a custom Python MCP server (the Cadence Brain Server)
that exposes:

- Semantic search across all brand documents
  PDFs, DOCX, TXT, MD - brand book, positioning docs, product briefs, SOPs

- Google Sheets integration
  Read/write inventory, content calendars, campaign logs via service account

- Auto-ingestion of new documents
  Drop a file into raw-docs/, it is automatically embedded into the RAG store
  within ~2 seconds (no terminal commands needed)

- Clean removal of documents
  Ask Claude to remove a document; the server deletes both the file reference
  and all its embeddings

- Note saving and retrieval
  Claude can save its own analysis into /outputs/ and read past notes later

Claude can now answer questions like:

- "What's our REST line positioning, and which products in Inventory have less
  than 14 days of stock?"
- "Summarise our brand voice guidelines and save it as a note."
- "List all Google Sheets connected, then read the Instagram tab from the
  Content sheet."


------------------------------------------------------------
3. ARCHITECTURE
------------------------------------------------------------

Claude Desktop
     |
     |  MCP Protocol (stdio)
     v
Cadence Brain Server  (cadence_brain_server.py)
     |-- ChromaDB               local vector store (embeddings/)
     |-- sentence-transformers  all-MiniLM-L6-v2, 80MB, free, local
     |-- watchdog               background file watcher (auto-ingest)
     |-- gspread                Google Sheets via service account

100% local compute and storage for documents and embeddings.
Only external calls are Google Sheets API requests via service account.


------------------------------------------------------------
4. TOOLS EXPOSED TO CLAUDE (12 TOTAL)
------------------------------------------------------------

search_knowledge_base(query)       Semantic search across all brand docs
list_documents()                   List indexed documents + chunk counts
ingest_new_documents()             Manually trigger indexing of new files
remove_document(filename)          Remove a document and all its embeddings
get_brand_context(topic)           Quick brand context (products, voice, lines)
add_note(title, content)           Save Claude's analysis to /outputs/
list_output_notes()                List saved analyses
read_output_note(filename)         Read a saved analysis file
list_all_spreadsheets()            List all Google Sheets shared with service account
read_sheet(spreadsheet, tab)       Read data from any tab by name
write_sheet(spreadsheet, tab, data) Append a row to any sheet
list_sheet_tabs(spreadsheet)       List all tabs in a spreadsheet

All tools are discoverable directly inside Claude Desktop via the MCP tools icon.


------------------------------------------------------------
5. HOW TO RUN IT
------------------------------------------------------------

PREREQUISITES
- Python 3.11+ installed
- Claude Desktop (Windows or Mac) installed
- Google Cloud project with Sheets API enabled
- A Google Sheet shared with a service account email

STEP 1 - Install dependencies

  pip install fastmcp chromadb sentence-transformers PyPDF2 python-docx gspread watchdog

STEP 2 - Set up folder structure

  cadence-brain/
    |-- cadence_brain_server.py    MCP server (all 12 tools)
    |-- ingest.py                  Initial ingestion script
    |-- requirements.txt
    |-- credentials.json           Google service account key (do not commit)
    |-- raw-docs/                  Drop brand docs here
    |-- embeddings/                ChromaDB vector store (auto-created)
    |-- outputs/                   Claude saves analyses here

Drop any PDFs, DOCX, TXT, or MD files into raw-docs/ then run:

  python ingest.py

After this, new files dropped into raw-docs/ are auto-indexed by the watchdog
file watcher. No extra commands needed.

STEP 3 - Google Sheets setup

1. In Google Cloud Console, create a service account and enable the Sheets API
2. Download the JSON key and save it as credentials.json in cadence-brain/
3. Share your target Google Sheets with the service account email (Editor access)

STEP 4 - Connect MCP server to Claude Desktop

Add this to claude_desktop_config.json (path depends on OS):

  {
    "mcpServers": {
      "cadence-brain": {
        "command": "python",
        "args": ["D:\AI\Anti\cadence-brain\cadence_brain_server.py"]
      }
    }
  }

Adjust the path to match where cadence_brain_server.py lives on your machine.
Restart Claude Desktop, open a new chat, and click the tools icon to confirm
all 12 tools are available.


------------------------------------------------------------
6. EXAMPLE PROMPTS TO TEST THE SYSTEM
------------------------------------------------------------

- "Search my knowledge base for REST line positioning."
- "Summarise our brand voice guidelines and save it as a note."
- "List all indexed documents and show their chunk counts."
- "List all my Google Sheets, then read the Instagram tab from the Content sheet."
- "Which products in the Inventory sheet have less than 14 days of stock?"
- "Remove competitor_research.pdf from the knowledge base."


------------------------------------------------------------
7. ZERO-COST HACK
------------------------------------------------------------

This build replaces several paid or heavyweight components with free alternatives:

- Local ChromaDB + sentence-transformers for embeddings
  Replaces: paid vector DB services or embeddings APIs (e.g. Pinecone, OpenAI Embeddings)

- Filesystem + custom MCP server for document access
  Replaces: hosted RAG services or document intelligence platforms

- gspread + Google Sheets for structured data
  Replaces: paid databases or dashboard tools

- Claude Desktop + MCP for interaction
  Replaces: paid orchestration platforms or middleware

Total additional infrastructure cost: $0


------------------------------------------------------------
8. WHY THIS IS BETTER THAN TAUGHT
------------------------------------------------------------

The Week 4 session covered:
- Using a generic Filesystem MCP for basic file access
- Running separate scripts for RAG ingestion
- Connecting Claude to one external tool at a time

This build goes beyond that in five ways:

1. Custom brand-specific MCP server instead of a generic Filesystem server
2. RAG + Sheets tools integrated into one server, not separate processes
3. Auto-ingestion via a background file watcher - new docs are live in ~2 seconds
4. Clean document removal with remove_document() that wipes references and embeddings
5. 12 coherent tools designed around Cadence's actual operations, not generic commands

This shifts MCP from basic file access to a persistent brand intelligence layer
for a real D2C company - materially beyond what was demonstrated in the session.


------------------------------------------------------------
9. COMPETITION DETAILS
------------------------------------------------------------

Event         AI Architect Simulation - Week 4
Company       Cadence (D2C nutritional supplements - DAILY, FORM, REST lines)
Role          Internal Brand Intelligence Assistant for strategy, content, and ops
Stack         Python, FastMCP, ChromaDB, sentence-transformers, gspread, watchdog
Cost          $0 (excluding Claude API and standard Google Sheets API usage)
