# Invoice Intelligence System
### Hackathon Submission - July 2026

> **AI-powered supply chain document intelligence for Indian SMEs — from raw PDFs to real-time ITC risk scores, vendor grades, cross-document exception flags, and a searchable Document Vault.**

Built in 8 days: June 29 – July 6, 2026. Extended with Phase 2 refinements: July 21–26, 2026. Deployed to GCP Cloud Run: July 29, 2026.

---

## The Problem

Small and mid-sized businesses in India deal with a paperwork-heavy, error-prone supply chain. A single purchase results in five documents: a Purchase Order, an Invoice, an E-Waybill, a Goods Receipt Note (GRN), and sometimes a Material Return Note. These documents arrive as PDFs across email, WhatsApp, and Google Drive — and no one is cross-checking them.

The consequences are real:

- **Missed ITC (Input Tax Credit):** Businesses lose GST credits because invoices don't match GSTR-2B filings or contain field errors. India's GST Council estimates billions in annual ITC leakage annually.
- **Vendor disputes:** Quantity shortfalls, transport mode violations, and early-expiry e-waybills go unnoticed until it's too late.
- **Manual reconciliation:** Finance teams spend hours every week matching invoices to POs by hand — a task that should take seconds.
- **No visibility:** There's no single place to see whether a PO has a matching invoice, whether goods arrived, or whether anything was returned.

**Who is this for?** Any Indian business with a procurement function — a manufacturing SME, a trading company, a distributor. The specific user is a Finance Manager or Accounts Payable team that processes 50–500 invoices per month and currently does reconciliation in spreadsheets.

---

## What It Does

The Invoice Intelligence System ingests documents from Google Drive, extracts structured data using LLMs, runs cross-document validation, and surfaces actionable risk signals through a web dashboard.

```
Google Drive (PDFs)
        │
        ▼
   OCR + LLM Extraction          ← Groq (Llama 3) + Google Gemini
   (Invoice / PO / Waybill /
    GRN / Material Return)
        │
        ▼
   PostgreSQL (Supabase)          ← Multi-tenant, row-level security
   Structured supply chain data
        │
        ├──► BigQuery             ← Live sync via streaming insert
        │    + cuDF/RAPIDS        ← GPU-accelerated analytics at scale
        │
        ▼
   FastAPI Backend
   Cross-document reconciliation engine
   Vendor scoring engine
   ITC eligibility engine
        │
        ▼
   React Dashboard
   ├── Invoice list with supply chain health indicators
   ├── Advanced Search (13-dimension filter panel)
   ├── Document Vault (file-first explorer across all doc types)
   ├── ITC Summary (Rule 42/43 compliance)
   ├── Vendor Scorecard (A–F grading)
   └── Analytics (ITC trend, vendor reliability — powered by BigQuery)
```

---

## The Data Pipeline

### 1. Ingestion — Google Drive + OCR

Documents are stored in six typed Google Drive folders (invoices, purchase orders, GSTR-2B, waybills, GRN, material returns). A sync job polls each folder, downloads new PDFs, and runs them through a text extraction pipeline:

- `pdfplumber` extracts text from digital PDFs
- Blank / image-only pages are detected early (< 50 chars threshold) and skipped to avoid wasting LLM tokens
- Long documents are sampled (head + tail) to stay within context limits

### 2. Extraction — LLM Structured Output

Each document type has a JSON Schema (`invoice_schema.json`, `po_schema.json`, `waybill_schema.json`, etc.). The extracted text is sent to **Groq (Llama 3.3 70B)** with the schema as a strict output format. If Groq fails or returns empty output, the pipeline falls back to **Google Gemini**.

Fields extracted per document type:

| Document | Key Fields |
|----------|-----------| 
| Invoice | vendor/buyer GSTIN, invoice number, date, line items with HSN codes, tax amounts, payment terms |
| Purchase Order | PO number, line items, Incoterms 2020 (all 11 codes), payment terms, advance %, delivery address |
| E-Waybill | EWB number, validity date, consignment value, transport mode, place of dispatch/delivery, document_number (invoice reference) |
| GRN | received quantities, rejection count, receipt date |
| Material Return | return quantities, reason, linked PO/GRN |

### 3. Storage — PostgreSQL with Row-Level Security

All structured data lands in Supabase (PostgreSQL). The schema is fully multi-tenant: every table carries `org_id` and is protected by row-level security policies. Key tables:

`invoices` → `line_items` → `purchase_orders` → `po_line_items` → `waybills` → `grn` → `material_returns` → `vendor_scores` → `exceptions`

Cross-document links are maintained via `po_number` (Invoice ↔ PO ↔ GRN ↔ MR) and `document_number` on waybills (stores the linked invoice number).

### 4. Analytics — BigQuery + NVIDIA cuDF/RAPIDS

After every sync, structured data streams into **BigQuery** for analytical queries. Two analytical views:

- `itc_summary_bigquery.sql` — aggregates eligible vs ineligible ITC per period, applying GST Rule 42/43 apportionment
- `vendor_score_bigquery.sql` — computes weighted vendor grades across the full document history

For scale testing, **cudf.pandas** (NVIDIA RAPIDS) replaces the standard pandas layer. Benchmarks showed **11.3× speedup at 20M rows** for the reconciliation and scoring computations. An SME processing invoices for 3–5 years accumulates this data volume quickly, and the reconciliation engine runs on every sync.

```python
import cudf.pandas
cudf.pandas.install()
import pandas as pd   # now GPU-accelerated transparently
```

The drop-in replacement required zero changes to existing analytics code.

### 5. Reconciliation Engine — 9 Cross-Document Checks

`POST /supply-chain/reconcile` runs nine checks across the full document chain and writes flagged anomalies to the `exceptions` table:

| Flag | Trigger | Severity |
|------|---------|----------|
| `transport_mode_mismatch` | PO requested mode ≠ Waybill actual mode | HIGH |
| `waybill_invoice_mismatch` | Waybill document number doesn't match any invoice | HIGH |
| `grn_quantity_short` | GRN received < PO ordered by > 2% | MEDIUM |
| `grn_quantity_over` | GRN received > PO ordered by > 2% | MEDIUM |
| `high_rejection_rate` | GRN rejected/received > 5% | HIGH |
| `material_returned` | Any MRN linked to this PO | HIGH |
| `missing_waybill` | Invoice exists, no waybill within 7 days | MEDIUM |
| `missing_grn` | Waybill exists, no GRN within 14 days | MEDIUM |
| `waybill_expired` | `ewb_valid_until` < GRN date | HIGH |

### 6. Vendor Scoring Engine

Every vendor gets a composite grade (A–F) recomputed on each sync:

| Factor | Weight |
|--------|--------|
| Quality rate (1 − returned/received) | 35% |
| On-time delivery | 20% |
| Invoice accuracy | 20% |
| Transport compliance | 15% |
| Advance payment risk | 10% (penalty) |

Critical overrides: high rejection rate in last 90 days caps score at C; two or more transport mismatches flag `logistics_non_compliant`; any expired waybill flags `compliance_risk`.

The scorer joins via `vendor_gstin` across all supply chain tables — the correct join key for Indian B2B document data where GSTIN is the universal vendor identifier.

---

## The Dashboard

The frontend is a React SPA (Vite) authenticated with Clerk.

### Invoice List
The primary view. Each row shows full supply-chain health at a glance:
- Linked document indicators for PO, Waybill, GRN, and Material Return (✅ / ⚠️ / ➖), gated on actual Drive file presence
- Computed pay-by date from payment terms (Net 30, days from GRN, COD, EOM, explicit due dates)
- HSN eligibility badge with exact match → 4-digit heading → 2-digit chapter match hierarchy
- Confidence score from LLM extraction
- Rescan button for any linked document type

### Advanced Search
An inline expanding panel (no modal, no sidebar) with 13 filter dimensions:
- **Backend filters:** status, vendor GSTIN, PO number, paid/unpaid, overdue only, date from/to
- **Client-side filters:** invoice number, waybill number, GRN number, MRN number, amount min/max
- Date presets: Today, This week, This month, Quarter, This year
- Amount slider for visual range selection alongside a text input

### Document Vault
A file-first explorer across all 5 document types. Shows every document that was scanned, including those with partial or failed extraction (null reference fields shown as italic rather than hidden). Features:
- Link status badges per document showing which related documents are connected
- Edit drawer with live link-match detection — a toast fires when a typed reference value matches an existing document, before saving
- Cross-field link matching (waybills link via `document_number`, not `ewb_number`)
- All 4 document PATCH routes fully functional with correct request body handling

### ITC Summary
Eligible credit per period, Rule 42/43 apportionment for mixed-use businesses, ineligible line items flagged.

### Vendor Scorecard
A–F grades with drill-down into contributing factors and override flags.

### Analytics
ITC trend over time and vendor reliability table, powered by live BigQuery queries. Updates automatically on every Drive sync.

---

## Training Data — Custom Synthetic B2B Document Generator

→ **[github.com/LeafyChan/Synthetic_B2B_Invoice_generator](https://github.com/LeafyChan/Synthetic_B2B_Invoice_generator)**

One of the first problems encountered was the complete absence of any public labelled dataset for Indian B2B documents. Real invoices contain sensitive GSTIN, PAN, and financial data that can't be shared. Rather than skip evaluation entirely, a fully custom synthetic document generator was built from scratch alongside the main system — during the same 8-day window.

### What it generates

Complete, linked five-document transaction sets — the same document chain the main system processes:

| Document | File prefix | Links to |
|----------|-------------|---------|
| Purchase Order | `po_NNNNNN` | — |
| Tax Invoice | `inv_NNNNNN` | PO number |
| E-Way Bill | `ewb_NNNNNN` | Invoice number |
| Goods Receipt Note | `grn_NNNNNN` | PO + Invoice |
| Material Return Note | `mrn_NNNNNN` | GRN (only when rejections exist) |

All five documents in a transaction set share the same `doc_index` for exact ground-truth cross-document linking. The MRN is conditional — it only appears when the GRN records a rejection, mirroring real procurement behaviour.

### GST-accurate field generation

- **HSN/SAC codes** looked up from the official government master using a TF-IDF index. Generated items get real 8-digit HSN codes with correct GST rate slabs.
- **All 11 Incoterms 2020** supported (EXW, FCA, DAP, DDP, FOB, CIF, etc.), weighted toward domestic Indian patterns.
- **Payment terms** cover the full range: advance %, net-days from GRN, LC at sight, COD, EOM, progress payments.
- **GSTIN** numbers are structurally valid (state code + PAN format).

### Deliberate discrepancies for model training

- **PO ↔ Invoice discrepancies** at configurable rates (default 15%): `quantity_mismatch`, `price_mismatch`, `extra_line_item`, `missing_line_item`, `gst_rate_mismatch`.
- **Transport mode discrepancy** (PO vs E-Way Bill) at ~1.5%.
- **GRN quantity shorts and overages**, rejection rates, and conditional MRN generation.

### Document realism — layout variation + degradation

- 8 layout variants for PO and Invoice, 4 for GRN, 3 each for MRN and E-Way Bill.
- Three degradation tiers: `clean` (pristine/laser), `degraded` (worn laser/archive scan), `heavy` (fax quality/tea-stained/crumpled).
- PDFs degraded by rasterising each page, applying OpenCV pipeline, then rebuilding the PDF.

### Architecture

```
Pass 1 - bootstrap.py (once per industry)
  LLM → product descriptions
  → TF-IDF HSN lookup → industry_catalog.json (~1,000 items with real codes + rates)

Pass 2 - assembler.py (parallel workers)
  For each doc_index:
    data_models.py         → PO + Invoice dataclasses, discrepancy injection
    supporting_docs.py     → adapt PO/Invoice → GRN/MRN/Waybill
    layout_engine*.py      → HTML templates (8+8+4+3+3 variants)
    renderer.py            → PNG + PDF via Playwright/Chromium
    degradation*.py        → tiered OpenCV degradation (PNG + PDF)
    database.py            → SQLite ground truth (documents, pairs, supporting_docs)
```

A 20,000-pair run (100,000 documents) completes with 4 parallel workers.

---

## Technology Stack

| Layer | Technology |
|-------|-----------|
| Document storage | Google Drive API |
| OCR | pdfplumber |
| LLM extraction | Groq (Llama 3.3 70B) + Google Gemini (fallback) |
| Transactional DB | Supabase (PostgreSQL) with RLS |
| Analytical DB | **Google BigQuery** |
| GPU acceleration | **NVIDIA cuDF / RAPIDS (cudf.pandas)** |
| Backend | FastAPI (Python), SQLAlchemy |
| Frontend | React, Vite, Clerk auth |
| Deployment | **GCP Cloud Run** (asia-south1) |

---

## Acceleration Evidence

### NVIDIA RAPIDS / cuDF

The reconciliation and vendor scoring pipelines process all line items, GRN records, and exception flags using pandas-style operations. Replacing `import pandas` with `cudf.pandas` (zero code changes) produced:

- **11.3× speedup at 20M rows** in `cudf_benchmark.py` (RTX 4050, CUDA 12)
- Streaming scale: 1,000 orgs · 100M rows · 11.9s · ~14MB peak RAM
- Enables full daily resync of multi-year invoice history in seconds rather than minutes

| Rows | pandas | cuDF | Speedup |
|------|--------|------|---------|
| 2M   | 0.188s | 0.098s | 1.9× |
| 5M   | 0.493s | 0.144s | 3.4× |
| 10M  | 1.099s | 0.129s | 8.5× |
| 20M  | 2.352s | 0.208s | **11.3×** |

### Google BigQuery

- Live streaming insert on every sync keeps analytics current without ETL lag
- ITC aggregation and vendor scoring run across the full historical dataset at the DB layer — no rows pulled to the application server
- Scales to any invoice volume without schema changes

---

## Real-World Impact

| Metric | Before | After |
|--------|--------|-------|
| Time to detect a GRN quantity short | Days (manual) | Seconds (auto-flagged on sync) |
| ITC reconciliation with GSTR-2B | Weekly, manual | Automatic on each sync |
| Vendor grade visibility | None | Real-time A–F with drill-down |
| Cross-document exception detection | Never | 9 check types, every sync |
| Finding a specific invoice or PO | Ctrl+F on spreadsheet | 13-dimension search panel |
| Debugging a failed extraction | Not possible | Document Vault shows every scanned row including partial failures |
| Resync time for 20M row history | ~2.4s (pandas) | ~0.2s (cuDF) |

---

## Setup

### Prerequisites
- Python 3.10+, Node 20+
- Supabase project, Google Cloud project with BigQuery enabled
- Google Drive API credentials (`gdrive_key.json`)
- Groq API key, Gemini API key, Clerk account

### Environment Variables
```bash
export GOOGLE_APPLICATION_CREDENTIALS="/path/to/bq_service_account.json"
export GDRIVE_KEY_PATH="/path/to/gdrive_key.json"
export GROQ_API_KEY="..."
export GEMINI_API_KEY="..."
export CLERK_JWKS_URL="https://<your-clerk-domain>/.well-known/jwks.json"
export DATABASE_URL="postgresql://..."
export SUPABASE_URL="https://<project>.supabase.co"
export SUPABASE_SERVICE_ROLE_KEY="..."
export BQ_PROJECT_ID="your-gcp-project"
export BQ_DATASET="invoice_intel"
export INVOICE_SCHEMA_PATH="/path/to/core/config/invoice_schema.json"
export PO_SCHEMA_PATH="/path/to/core/config/po_schema.json"
export CORE_PIPELINE_PATH="/path/to/personal_project"
```

### Database
Run migrations in order via Supabase SQL editor:
1. `schema.sql`
2. `migration_add_po_gstr2b_exceptions.sql`
3. `migration_add_training_exports.sql`
4. `migration_add_supply_chain.sql`
5. Phase 2 migrations (see Deployment Guide)

### Local Backend
```bash
pip install -r webapp/backend/requirements.txt
cd webapp/backend
python -m uvicorn app.main:app --reload --port 8000
```

### Local Frontend
```bash
cd webapp/frontend
npm install --legacy-peer-deps
npm run dev
```

### Dev Shorthands
```bash
source ~/personal_project/dev.sh   # load once (or add to ~/.bashrc)

start        # boot local backend + ngrok tunnel
rebuild      # frontend rebuild + restart local app
fdev         # Vite dev server with hot reload (localhost:3000)
logs         # watch backend logs live
fulldeploy   # frontend build → Docker build → Cloud Run deploy
crlogs       # tail Cloud Run logs
```

### Cloud Run Deployment
```bash
cd ~/personal_project
gcloud builds submit --config cloudbuild.yaml .
gcloud run deploy invoice-intel \
  --image asia-south1-docker.pkg.dev/apac-01072016/invoice-intel/invoice-intel:latest \
  --platform managed --region asia-south1 --allow-unauthenticated \
  --port 8080 --memory 2Gi --cpu 2 \
  --set-env-vars "BQ_PROJECT_ID=...,..."
```

### GPU Acceleration (optional, local only)
```bash
pip install cudf-cu12  # requires CUDA 12, NVIDIA GPU
# No code changes needed - cudf.pandas is a drop-in replacement
```

---

## Project Structure

```
invoice-intelligence/
├── core/
│   ├── config/               # JSON schemas for each document type
│   ├── pipeline.py           # Orchestration
│   ├── extractor.py          # Invoice LLM extraction
│   ├── waybill_extractor.py  # Waybill extraction
│   ├── grn_extractor.py      # GRN extraction
│   ├── material_return_extractor.py
│   ├── reconciliation.py     # Cross-document validation
│   ├── vendor_scorer.py      # A–F grading engine (joins via vendor_gstin)
│   └── gstr2b_parser.py      # GSTR-2B matching
├── scripts/
│   ├── bigquery_sync.py      # BQ live sync
│   ├── cudf_benchmark.py     # GPU benchmark (11.3× at 20M rows)
│   └── multi_org_benchmark_final.py  # 1000-org streaming benchmark
├── sql/
│   ├── itc_summary_bigquery.sql
│   └── vendor_score_bigquery.sql
├── Dockerfile                # Cloud Run image (requirements_cloudrun.txt)
├── cloudbuild.yaml           # GCP Cloud Build config
├── dev.sh                    # Dev shorthands (source to load)
└── webapp/
    ├── backend/
    │   ├── requirements.txt           # Local venv (full, with GPU/CUDA)
    │   ├── requirements_cloudrun.txt  # Cloud Run (no GPU packages)
    │   └── app/              # FastAPI application (40+ endpoints)
    └── frontend/src/
        ├── InvoiceList.jsx   # Primary view with supply chain indicators
        ├── AdvancedSearch.jsx  # 13-dimension inline search panel
        ├── DocumentVault.jsx   # File-first doc explorer with edit drawer
        ├── ReviewModal.jsx     # Multi-doc tabbed viewer
        ├── VendorScorecard.jsx
        ├── Itcsummary.jsx
        └── Analytics.jsx     # BigQuery ITC trend + vendor reliability

Synthetic_B2B_Invoice_generator/  # companion repo
├── bootstrap.py              # LLM → industry catalog generation
├── assembler.py              # Parallel document generation
├── data_models.py            # PO + Invoice dataclasses + discrepancy injection
├── supporting_docs.py        # GRN / MRN / Waybill derivation
├── layout_engine_*.py        # HTML templates (26 total variants)
├── renderer.py               # PNG + PDF via Playwright
├── degradation_*.py          # OpenCV tiered degradation pipeline
└── database.py               # SQLite ground-truth store
```

---

## Phase 2 — Post-Submission Refinements (July 21–26, 2026)

Phase 2 fixed 13 issues identified during live testing and added two major features:

### Advanced Search
A 13-dimension inline search panel replacing the basic status dropdown. Filters split between backend (date range, vendor GSTIN, PO number, paid/overdue status) and client-side (invoice/waybill/GRN/MRN number, amount range). Date presets compute from the current date; manual From/To inputs work for any date range.

### Document Vault
A file-first view across all 5 document types. Every document that was scanned is visible regardless of extraction quality — partial failures are shown with null fields rather than hidden. An edit drawer allows manual correction of reference fields with real-time link-match detection. Fixed cross-field link matching using a `[targetType, targetField]` tuple format in the LINK_MAP so asymmetric links (waybill's `document_number` storing the invoice number, rather than `ewb_number`) resolve correctly.

### Backend fixes
- All 4 PATCH routes (PO, waybill, GRN, MRN) fixed with `Body(...)` — were silently 500ing on valid requests
- `vendor_scorer.py` rewritten to join via `vendor_gstin` throughout (was querying non-existent `vendor_id` FK columns, silently returning grade A for every vendor)
- `POST /vendors/scorecard/recalculate-all` endpoint added
- `PATCH /invoices/{id}/unmark-paid` added
- Date filter WHERE clause placement bug fixed in `list_invoices`
- `processed_at` column added to waybills, grn, and material_returns tables (vault endpoints were 500ing without it)

---

## S24–S25 — Cloud Run Deployment (July 28–29, 2026)

- Bug 20 fixed: BQ UUID serialization — `str()` all UUID fields before `insert_rows_json`; analytics charts now populate correctly
- GPU card removed from Analytics tab — benchmarks run locally, not in the deployed app
- Deployed to GCP Cloud Run: `https://invoice-intel-542954306088.asia-south1.run.app`
- `requirements_cloudrun.txt` pinned to exact versions matching local venv (minus all GPU/CUDA packages)
- `dev.sh` shorthand script added (`fulldeploy`, `crlogs`, `crrev`, `start`, `rebuild`, `fdev`, etc.)

---

## What's Next

- Mobile-responsive layout for on-the-go invoice approval
- Custom OCR trained specifically on Indian handwritten business documents
- GSTR-2B reconciliation end-to-end (data model supports it, reconciliation engine not yet wired)
- Improve `material_return_extractor.py` to reliably extract return quantities (Bug 52)
- Fix Bug 21: `line_items_flat` BQ table missing `org_id` column