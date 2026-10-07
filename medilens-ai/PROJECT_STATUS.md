# MediLens AI — Project Status

## Phase 1 — Backend Foundation: COMPLETE

### Initial inspection
No existing project, backend, `requirements.txt`, `.env`, or routes were found
in the working environment, so the backend was created from scratch.
Python version: 3.12.3.

### What was completed
- FastAPI application factory (`create_app`)
- Environment-based configuration (`pydantic-settings`, reads `.env`)
- CORS middleware (origins configurable via `CORS_ORIGINS`)
- `GET /api/v1/health` endpoint
- Basic error handling with a consistent JSON shape
  (`{"error": {"code": ..., "message": ...}}`) for HTTP errors,
  validation errors (422) and unhandled exceptions (500)
- Tests, `requirements.txt`, `.env.example`, `.gitignore`, run script

### Files created
```
backend/
├── app/
│   ├── __init__.py
│   ├── main.py
│   ├── core/
│   │   ├── __init__.py
│   │   └── config.py
│   └── routers/
│       ├── __init__.py
│       └── health.py
├── tests/
│   ├── __init__.py
│   └── test_health.py
├── .env.example
├── .gitignore
├── requirements.txt
└── run.py
PROJECT_STATUS.md
```
No existing files were changed or deleted. No `.env` was read or created.

### Dependencies added
| Package | Purpose |
|---|---|
| fastapi | Web framework |
| uvicorn[standard] | ASGI server |
| pydantic-settings | Config / env loading |
| pytest | Tests (dev) |
| httpx | Required by FastAPI's TestClient (dev) |

### API endpoint
| Method | URL | Response |
|---|---|---|
| GET | `/api/v1/health` | `{"status": "ok"}` |

Interactive docs: `http://127.0.0.1:8000/docs`

### How to start the backend
```bash
cd backend
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env             # Windows: copy .env.example .env
python run.py
```
Then open http://127.0.0.1:8000/api/v1/health

### How to run tests
```bash
cd backend
python -m pytest -v
```

### Tests completed
- `test_health_returns_ok` — GET /api/v1/health returns 200 and `{"status": "ok"}` ✅
- `test_unknown_route_returns_json_error` — 404 uses the JSON error shape ✅
- `test_cors_allows_configured_origin` — CORS header set for configured origin ✅

Result: 3 passed. Live server also verified with `curl` (HTTP 200).

### Known note
Starlette's TestClient emits a deprecation warning about `httpx`
(suggests `httpx2`). It is harmless; tests pass. Revisit if it becomes an issue.

---

## Phase 2 — Report Upload: COMPLETE

Local-development upload and validation of medical report files.
No OCR, AI, chatbot, comparison, multilingual, Supabase or auth work was done.

### What was completed
- `POST /api/v1/reports/upload` (multipart/form-data, one file in field `file`)
- Validation of extension, declared MIME type, **and real content (magic bytes)**
- Configurable size limit, enforced while streaming to disk
- Filename sanitizing and app-controlled storage paths (UUID directory per report)
- Storage logic in a service; router is thin
- Errors reuse the Phase 1 JSON shape: `{"error": {"code": ..., "message": ...}}`

### Endpoint
| Method | URL | Success |
|---|---|---|
| POST | `/api/v1/reports/upload` | `201 Created` |

Response (Pydantic model `ReportUploadResponse`):
```json
{
  "report_id": "0385c4c0-5182-4352-8e1a-19447962081d",
  "filename": "example.pdf",
  "file_type": "application/pdf",
  "file_size": 123456,
  "status": "uploaded"
}
```
`filename` is the client's original name (path-stripped) and is metadata only.
`file_type` is the type detected from the file content.

Errors:
| Status | When |
|---|---|
| 400 | Empty file; content does not match extension/declared type |
| 413 | File larger than the limit |
| 415 | Unsupported extension, declared type, or content |
| 422 | Missing `file` field / not multipart (Phase 1 validation handler) |
| 500 | Storage failure (generic message, no paths exposed) |

### Supported file types
| Type | Extensions | Content check |
|---|---|---|
| PDF | `.pdf` | starts with `%PDF-` |
| JPEG | `.jpg`, `.jpeg` | starts with `FF D8 FF` |
| PNG | `.png` | starts with the 8-byte PNG signature |

The extension, the declared `Content-Type`, and the detected content must all agree.

### Maximum file size
Default **10 MB**, set by `MAX_UPLOAD_SIZE_MB` in `.env`. Defined once in
`Settings.max_upload_size_bytes`; the storage service reads it from there.

### Storage location
`backend/storage/reports/<report_id>/<sanitized_filename>`
(set by `REPORT_STORAGE_PATH`; relative paths resolve against `backend/`, not the CWD).
- `report_id` is a server-generated UUID4. The original filename is never used as an identifier.
- Files are created with exclusive-create mode, so nothing is ever overwritten.
- `storage/reports/*` is git-ignored (uploads may contain personal medical data).

### Filename safety
Directory parts (`/`, `\`) and control characters are stripped; only `[A-Za-z0-9._-]`
is kept; leading dots, `..` sequences and Windows reserved names (`CON`, `NUL`, ...) are
neutralized; names are length-limited. If nothing usable remains (e.g. a name written
entirely in non-Latin script) the stored name falls back to `report<ext>`. The original
name is still returned in the response metadata.

### Files created
```
backend/
├── app/
│   ├── core/errors.py                 (new)  upload error classes
│   ├── models/__init__.py             (new)
│   ├── models/schemas.py              (new)  ReportUploadResponse
│   ├── routers/reports.py             (new)  POST /reports/upload
│   ├── services/__init__.py           (new)
│   ├── services/file_validation.py    (new)  magic bytes, type checks, sanitizing
│   └── services/storage.py            (new)  ReportStorage + get_report_storage
├── storage/reports/.gitkeep           (new)
└── tests/
    ├── conftest.py                    (new)  temp-dir storage fixture
    ├── helpers.py                     (new)  synthetic PDF/PNG/JPEG bytes
    ├── test_upload.py                 (new)
    ├── test_file_validation.py        (new)
    └── test_config.py                 (new)
```

### Files changed
- `app/core/config.py` — added `MAX_UPLOAD_SIZE_MB`, `REPORT_STORAGE_PATH`,
  `max_upload_size_bytes`, `report_storage_dir`, `BASE_DIR`
- `app/main.py` — registered the reports router (2-line change)
- `requirements.txt` — added `python-multipart`
- `.env.example` — added the two new variables
- `.gitignore` — ignore uploaded reports

Phase 1 code and tests were otherwise left intact.

### Dependencies added
| Package | Purpose |
|---|---|
| python-multipart | Required by FastAPI to parse `multipart/form-data` uploads |

### Tests performed
`python -m pytest -v` → **65 passed** (3 Phase 1 + 62 Phase 2). Tests use only
synthetic files and a temporary storage directory.
- Valid PDF, PNG, JPEG/JPG uploads (file saved at `<root>/<report_id>/<name>`, bytes identical)
- Upload exactly at the size limit is accepted
- Unsupported types: `.txt`, `.exe`, `.html`, `.gif`, no extension, wrong declared type, fake PDF text
- Disguised files: PNG named `.pdf`, PDF named `.png`, extension/declared-type conflicts
- Empty file
- File over the limit (incl. multi-chunk) rejected, and no partial file/directory left behind
- Report IDs are unique valid UUID4, not derived from the filename; same filename never overwrites
- 11 path-traversal / unsafe-name cases (`../`, `..\`, absolute and Windows paths, URL-encoded,
  shell characters, non-ASCII): all contained inside the storage root
- Missing field, non-multipart body, wrong HTTP method
- Storage failure returns a generic 500; no error response leaks filesystem paths
- Config: defaults, env override, relative/absolute storage path, non-positive limit rejected
- Filename sanitizer and content-type detection unit tests

Manual check with the live server and `curl`: valid PDF/PNG/JPG (201), unsupported
(415), empty (400), oversize with `MAX_UPLOAD_SIZE_MB=1` (413), disguised file (400),
traversal filename (201, contained and renamed), missing field (422).

### How to manually test
```bash
cd backend
python run.py
# in another terminal:
curl -i -F "file=@/path/to/sample.pdf;type=application/pdf" \
  http://127.0.0.1:8000/api/v1/reports/upload
```
Or use the Swagger UI at http://127.0.0.1:8000/docs (`POST /api/v1/reports/upload`
-> "Try it out"). Use synthetic files only.

### Limitations
- **Size limit is enforced after the request is received.** Starlette parses the
  multipart body (spooling to a temp file) before our code runs, so an oversized
  upload is rejected with 413 but its bytes still reach the server first. A
  reverse proxy limit (e.g. nginx `client_max_body_size`) is the production answer.
- Content check is by file signature only; it does not prove a file is a well-formed or
  non-malicious PDF/image. Malware scanning and image/PDF structure validation are out of scope.
- PDFs must start with `%PDF-` at byte 0. A few legitimate PDFs with leading junk bytes
  would be rejected.
- The declared `Content-Type` must be exact (`application/pdf`, `image/jpeg`,
  `image/png`). Clients sending `application/octet-stream` are rejected.
- No metadata record is stored: the original filename is not persisted (only returned
  in the upload response), and there is no endpoint to list or fetch reports yet.
- No authentication, rate limiting, quotas, or cleanup of old uploads.
- Local disk only (development). Not suitable for production or for real patient data.
- Starlette's `httpx` TestClient deprecation warning from Phase 1 remains (harmless).

### Next phase (Phase 3 — not started): text extraction
Extract text from uploaded reports (PDF text layer, then images). Phase 2 provides
`ReportStorage` / `StoredReport` and the `<report_id>/` layout to build on. Open
decisions for that phase: persisting upload metadata (e.g. original filename), and how
to look up a stored file by `report_id`.
