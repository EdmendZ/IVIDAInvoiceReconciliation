# IVIDA Invoice Reconciliation Operations

## Runtime components

The pilot has three independently restartable processes:

1. FastAPI on `http://127.0.0.1:8200`
2. extraction Worker, which submits and polls MinerU and calls the text normalizer
3. review UI on `http://127.0.0.1:5274`

PostgreSQL is the source of truth for tasks, runs, drafts, versions, audit actions
and reconciliation results. MinIO stores originals and MinerU ZIP artifacts.

## First-time setup

Configure the ignored `.env`. Never commit API keys. The MinerU token previously
disclosed in chat must be revoked and replaced before a paid run.

Required extraction settings:

```dotenv
MINERU_API_TOKEN=REPLACE_WITH_ROTATED_TOKEN
MINERU_BASE_URL=https://mineru.net/api/v4
MINERU_MODEL=vlm
MINERU_LANGUAGE=en
NORMALIZATION_BASE_URL=https://YOUR_OPENAI_COMPATIBLE_ENDPOINT/v1
NORMALIZATION_API_KEY=REPLACE_ME
NORMALIZATION_MODEL=YOUR_TEXT_MODEL
```

Apply migrations:

```powershell
Set-Location E:\ZephyrLLM\Projects\IVIDAInvoiceReconciliation
.\.venv\Scripts\python.exe init_database.py
```

Create a persistent account. The password prompt is hidden and requires at least
12 characters:

```powershell
.\.venv\Scripts\python.exe -m app.cli.create_admin --username reviewer --role reviewer
```

Use `--role admin` only for staff who may configure Providers or retry failed
runs.

## Startup

Open three terminals:

```powershell
# Terminal 1
.\.venv\Scripts\python.exe run_api.py

# Terminal 2
.\.venv\Scripts\python.exe run_extraction_worker.py

# Terminal 3
.\run_review_frontend.ps1
```

Open `http://127.0.0.1:5274`.

The browser UI now covers the pilot workflow:

- **Upload** stores a PDF/image, queues extraction and polls durable task state.
- **Review** exposes normalized JSON, source evidence and validation issues.
- **Reconcile** lists only approved versions and renders persisted line results.

Swagger remains useful for diagnostics, but is no longer required for the normal
upload-to-reconciliation workflow.

## Business workflow

1. Upload an Invoice or Receive Note using `POST /api/documents/upload`.
2. Queue it with `POST /api/extraction-tasks/{task_id}/extract`.
3. The Worker persists the MinerU artifact, normalized draft, evidence and issues.
4. A reviewer opens the queue, corrects fields and saves a new version.
5. Blocking arithmetic or GST issues must be resolved before approval.
6. Approval makes the version immutable; audit actions remain append-only.
7. Submit approved version IDs to `POST /api/reconciliations`.
8. PostgreSQL persists the reconciliation header, Receive Note links and line results.

The raw JSON comparison endpoint is retained for development diagnostics. It must
not be used as the production approval path.

## Recovery

- API restart: safe; queued work remains in PostgreSQL.
- Worker restart: safe after the lease expires. The next Worker reclaims the run.
- Failed MinerU call: stored with a stable phase error code and safe message.
- MinIO outage: the run fails without creating a partial draft.
- Approved version: cannot be updated or deleted by the application or directly
  in PostgreSQL because the database trigger rejects it.

## Backup boundary

Back up PostgreSQL and the `ivida-invoice-documents` MinIO bucket together.
Database rows reference MinIO object keys, so restoring only one side produces an
incomplete audit record.
