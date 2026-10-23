# CT-200 Traceable QA API

A focused FastAPI backend for extracting the CardioTrack CT-200 manual into a versioned hierarchy, pinning selections to immutable source text, generating structured QA ideas, and exposing staleness when the manual changes.

## Design summary

- **PDF parsing:** PyMuPDF text extraction first. If a page has almost no text, the parser attempts Tesseract OCR (install the Tesseract executable separately and ensure it is on PATH); OCR failures are returned as warnings. This assignment's PDFs have a usable text layer, so direct extraction is the primary path.
- **Tree reconstruction:** numbered headings are recognized from the CT-200 convention. Nodes retain encounter order, heading text, body text, parent version-node ID, logical node ID, and SHA-256 content hash. The parser flags skipped numbered parents rather than hiding the anomaly. Lists and table-like content are retained as text; complex table cell geometry is not reconstructed yet.
- **Versioning:** every ingestion gets an immutable `DocumentVersion` and separate `NodeVersion` records. `LogicalNode` IDs are matched one-to-one across versions using normalized heading and parent identity, with a normalized-heading fallback. This handles stable section headings and avoids collapsing repeated headings into one node. Reordered sections, same-heading siblings, and heading renames can still challenge this heuristic; inspect the match report and use manual review for ambiguous matches.
- **Selection pinning:** selections store the exact node-version IDs, text, and hashes used at creation. Later ingestion cannot change historical selection content.
- **Generation store:** generated artifacts are JSON documents under `generated/`, a deliberate no-service local alternative to MongoDB. Each artifact stores the source snapshot, hashes, selection ID and cases. It can be swapped for MongoDB without changing the API contract.
- **LLM:** `LLM_PROVIDER=groq` enables Groq's OpenAI-compatible JSON mode. The default `mock` provider produces deterministic, schema-valid sample cases so the full lifecycle can be tested without credentials. Pydantic validation rejects malformed/incomplete output; invalid output is never persisted. This implementation fails closed rather than attempting an unbounded repair loop.
- **Staleness:** exact hashes report `unchanged`, `changed`, or `removed` at retrieval time. Changed content is explicitly marked `not_automatically_assessed`; the system does not pretend a text diff proves clinical impact. A wording change and a threshold change are both detected, but priority/severity classification remains a human review task.

## Setup (Windows PowerShell)

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

Keep the supplied files at `data/ct200_manual.pdf` and `data/ct200_manual_v2.pdf` (they are included in this repository's working copy). Run:

```powershell
uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000/docs` for interactive API documentation.

## Ingest v1 and v2

Use the convenience route:

```powershell
curl -X POST http://127.0.0.1:8000/demo/ingest-bundled
```

Or upload each PDF separately to `POST /documents/ingest` using multipart form field `file`. The same exact file hash is idempotent and will not create a duplicate version. The first distinct PDF becomes version 1 and the next becomes version 2.

## End-to-end flow

1. `GET /documents/ct200-manual/sections?version=1`
2. Select a returned `node_id` and call `POST /selections` with `{"name":"Battery life","version":1,"node_ids":["<version-1-node-id>"]}`.
3. Call `POST /generations` with `{"selection_id":"<selection-id>"}`.
4. Ingest v2 if not already ingested.
5. Call `GET /generations?selection_id=<selection-id>` and inspect each source's `staleness` status.

Use `GET /nodes/search?q=battery&version=1` to find a node. Use `GET /nodes/{node_id}` for the node, hash and children. Use `GET /nodes/{logical_node_id}/changes` for version history. `GET /generations?node_id=<version-node-id-or-logical-id>` retrieves cases associated with a source node.

## LLM configuration

Set `LLM_PROVIDER=groq` and `GROQ_API_KEY` in `.env`. Optionally set `GROQ_MODEL`. The app loads `.env` using `python-dotenv`; process environment variables take precedence. `LLM_PROVIDER` accepts only `mock` or `groq`; an unsupported value is reported as an error rather than silently switching to mock output. The default is `mock` and requires no network or API key. Restart the server after changing environment variables.

Other optional settings in `.env.example` are `DATABASE_URL` (defaults to local SQLite at `./ct200.db`) and `GENERATIONS_DIR` (defaults to `./generated`).

For scanned-page OCR fallback, the Python `pytesseract` wrapper is installed with requirements, but the Tesseract OCR executable must also be installed separately and available on `PATH`. If it is missing, the parser emits an extraction warning rather than silently claiming OCR succeeded.

## End-to-end demonstration

Run this from the repository root. It uses an isolated temporary SQLite database and JSON output directory, ingests both supplied PDFs, verifies same-file ingestion is idempotent, creates a v1 selection, generates test ideas, ingests v2, and asserts the old generation is reported as changed:

```powershell
python scripts/demo_flow.py
```

## Tests

```powershell
python -m pytest -q
```

Tests cover duplicate headings with distinct parents, out-of-order sections, skipped hierarchy levels, numbered list items, hash changes, table-like text retention, Groq bearer-token configuration, and rejection of unsupported LLM providers.

## Limitations

- CT-200-specific numbered-heading parsing, not a universal PDF parser.
- PDF reading order and text extraction can flatten tables; the pipeline retains table-like rows but does not guarantee full cell reconstruction.
- Matching is heuristic. Identical repeated headings under the same parent can still be ambiguous; content similarity is not used as a definitive identity signal.
- Staleness is content-based and conservative. It flags change but does not determine regulatory significance.
- JSON files are appropriate for a single-process assignment demo, not concurrent production writes. MongoDB and atomic/versioned writes would be preferable in production.
