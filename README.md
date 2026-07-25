# Invoice Intelligence System
### Hackathon Submission - July 2026

> **AI-powered supply chain document intelligence for Indian SMEs - from raw PDFs to real-time ITC risk scores, vendor grades, and cross-document exception flags.**

Built in 8 days: June 29 – July 6, 2026.

---

## The Problem

Small and mid-sized businesses in India deal with a paperwork-heavy, error-prone supply chain. A single purchase results in five documents: a Purchase Order, an Invoice, an E-Waybill, a Goods Receipt Note (GRN), and sometimes a Material Return Note. These documents arrive as PDFs across email, WhatsApp, and Google Drive - and no one is cross-checking them.

The consequences are real:

- **Missed ITC (Input Tax Credit):** Businesses lose GST credits because invoices don't match GSTR-2B filings or contain field errors. India's GST Council estimates billions in annual ITC leakage annually.
- **Vendor disputes:** Quantity shortfalls, transport mode violations, and early-expiry e-waybills go unnoticed until it's too late.
- **Manual reconciliation:** Finance teams spend hours every week matching invoices to POs by hand - a task that should take seconds.
- **No visibility:** There's no single place to see whether a PO has a matching invoice, whether goods arrived, or whether anything was returned.

**Who is this for?** Any Indian business with a procurement function - a manufacturing SME, a trading company, a distributor. The specific user is a Finance Manager or Accounts Payable team that processes 50–500 invoices per month and currently does reconciliation in spreadsheets.

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
   ├── ITC Summary (Rule 42/43 compliance)
   ├── Vendor Scorecard (A–F grading)
   ├── Exceptions queue (9 auto-detected flag types)
   └── Analytics (ITC trend, vendor reliability)
```

---

## The Data Pipeline

### 1. Ingestion - Google Drive + OCR

Documents are stored in six typed Google Drive folders (invoices, purchase orders, GSTR-2B, waybills, GRN, material returns). A sync job polls each folder, downloads new PDFs, and runs them through a text extraction pipeline:

- `pdfplumber` extracts text from digital PDFs
- Blank / image-only pages are detected early (< 50 chars threshold) and skipped to avoid wasting LLM tokens
- Long documents are sampled (head + tail) to stay within context limits

### 2. Extraction - LLM Structured Output

Each document type has a JSON Schema (`invoice_schema.json`, `po_schema.json`, `waybill_schema.json`, etc.). The extracted text is sent to **Groq (Llama 3.3 70B)** with the schema as a strict output format. If Groq fails or returns empty output, the pipeline falls back to **Google Gemini**.

Fields extracted per document type:

| Document | Key Fields |
|----------|-----------|
| Invoice | vendor/buyer GSTIN, invoice number, date, line items with HSN codes, tax amounts, payment terms |
| Purchase Order | PO number, line items, Incoterms 2020 (all 11 codes), payment terms, advance %, delivery address |
| E-Waybill | EWB number, validity date, consignment value, transport mode, place of dispatch/delivery |
| GRN | received quantities, rejection count, receipt date |
| Material Return | return quantities, reason, linked PO/GRN |

### 3. Storage - PostgreSQL with Row-Level Security

All structured data lands in Supabase (PostgreSQL). The schema is fully multi-tenant: every table carries `org_id` and is protected by row-level security policies. Key tables:

`invoices` → `line_items` → `purchase_orders` → `po_line_items` → `waybills` → `grn` → `material_returns` → `vendor_scores` → `exceptions`

Cross-document links are maintained via `po_number` (Invoice ↔ PO ↔ GRN ↔ MR) and `invoice_number` (Invoice ↔ Waybill).

### 4. Analytics - BigQuery + NVIDIA cuDF/RAPIDS

After every sync, structured data streams into **BigQuery** for analytical queries. Two analytical views:

- `itc_summary_bigquery.sql` - aggregates eligible vs ineligible ITC per period, applying GST Rule 42/43 apportionment
- `vendor_score_bigquery.sql` - computes weighted vendor grades across the full document history

For scale testing, **cudf.pandas** (NVIDIA RAPIDS) replaces the standard pandas layer. Benchmarks showed **6.8× speedup at 2M rows** for the reconciliation and scoring computations. This matters because an SME processing invoices for 3–5 years accumulates this data volume quickly, and the reconciliation engine runs on every sync.

```python
import cudf.pandas
cudf.pandas.install()
import pandas as pd   # now GPU-accelerated transparently
```

The drop-in replacement required zero changes to existing analytics code.

### 5. Reconciliation Engine - 9 Cross-Document Checks

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

---

## Training Data - Custom Synthetic B2B Document Generator

→ **[github.com/LeafyChan/Synthetic_B2B_Invoice_generator](https://github.com/LeafyChan/Synthetic_B2B_Invoice_generator)**

One of the first problems encountered was the complete absence of any public labelled dataset for Indian B2B documents. Real invoices contain sensitive GSTIN, PAN, and financial data that can't be shared. Rather than skip evaluation entirely, a fully custom synthetic document generator was built from scratch alongside the main system - during the same 8-day window.

### What it generates

The generator produces complete, linked five-document transaction sets - the same document chain the main system processes:

| Document | File prefix | Links to |
|----------|-------------|---------|
| Purchase Order | `po_NNNNNN` | - |
| Tax Invoice | `inv_NNNNNN` | PO number |
| E-Way Bill | `ewb_NNNNNN` | Invoice number |
| Goods Receipt Note | `grn_NNNNNN` | PO + Invoice |
| Material Return Note | `mrn_NNNNNN` | GRN (only when rejections exist) |

All five documents in a transaction set share the same `doc_index` for exact ground-truth cross-document linking. The MRN is conditional - it only appears when the GRN records a rejection, mirroring real procurement behaviour.

### GST-accurate field generation

Documents aren't random filler. Every generated document is grounded in Indian GST law:

- **HSN/SAC codes** are looked up from the official government master (`HSN_SAC.xlsx`) using a TF-IDF index built over real product descriptions. Generated items get real 8-digit HSN codes with correct GST rate slabs.
- **All 11 Incoterms 2020** are supported on POs (EXW, FCA, DAP, DDP, FOB, CIF, etc.), weighted toward the domestic patterns (DAP/DDP/Road) that Indian SMEs actually use.
- **Payment terms** cover the full range: advance %, net-days from GRN, LC at sight, COD, EOM, progress payments.
- **GSTIN** numbers are structurally valid (state code + PAN format).

### Deliberate discrepancies for model training

The generator injects controlled discrepancies to teach the extraction and reconciliation pipeline what errors look like:

- **PO ↔ Invoice discrepancies** at a configurable rate (default 15%): `quantity_mismatch`, `price_mismatch`, `extra_line_item`, `missing_line_item`, `gst_rate_mismatch`. Each is deterministic per `doc_index` so ground truth is always known.
- **Transport mode discrepancy** (PO vs E-Way Bill) at ~1.5%, logged to SQLite as `transport_discrepancy = 1` and rendered as a visible warning banner on the EWB.
- **GRN quantity shorts and overages**, rejection rates, and conditional MRN generation all mirror the exact cross-document flags the reconciliation engine detects in production.

### Document realism - layout variation + degradation

To prevent models from learning layout shortcuts:

- **Multiple layout variants per document type:** 8 variants for PO and Invoice, 4 for GRN, 3 each for MRN and E-Way Bill. No two consecutive `doc_index` values share the same layout.
- **Three degradation tiers** applied via an OpenCV pipeline to both PNG and PDF output:

| Tier | Profiles | Effects |
|------|----------|---------|
| `clean` | pristine, laser, high-res | Near-zero noise, no rotation |
| `degraded` | worn laser, inkjet, archive scan | Visible noise, light stains, mild crumple, slight rotation |
| `heavy` | fax quality, tea-stained, crumpled, dying cartridge | Heavy stains, warp, resolution loss, rotation ±2.5° |

PDFs are degraded by rasterising each page, applying the OpenCV pipeline, then rebuilding the PDF - so the model trains on degraded PDFs, not just degraded images.

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

A 20,000-pair run (100,000 documents) completes with 4 parallel workers. The SQLite ground-truth database records every field value for every document so extraction accuracy can be measured exactly.

### How it feeds the main system

The `training_exports` table stores human-verified extractions from real documents. The synthetic generator fills the other side: large-scale labelled data for evaluating and stress-testing the extraction prompts, without any real business data leaving anyone's hands.

```
Synthetic generator → labelled training data → tune extraction prompts
Real documents      → human verification     → training_exports table → evaluate
```

---

## The Dashboard

The frontend is a React SPA (Vite + Tailwind) authenticated with Clerk.

**Invoice List** - The primary view. Each row shows full supply-chain health at a glance:
- Linked document indicators for PO, Waybill, GRN, and Material Return (✅ / ⚠️ / ➖)
- Computed pay-by date from payment terms (Net 30, days from GRN, COD, EOM, explicit due dates)
- HSN eligibility badge with chapter/heading-level match detail
- Confidence score from LLM extraction
- Rescan button for any linked document type

**ITC Summary** - Eligible credit per period, Rule 42/43 apportionment for mixed-use businesses, ineligible line items flagged.

**Vendor Scorecard** - A–F grades with drill-down into contributing factors and override flags.

**Exceptions Queue** - Auto-detected anomalies with severity, linked documents, and one-click resolution.

**Analytics** - ITC trend over time, vendor reliability charts, powered by BigQuery queries.

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
| Frontend | React, Vite, Tailwind CSS, Clerk auth |

---

## Acceleration Evidence

### NVIDIA RAPIDS / cuDF

The reconciliation and vendor scoring pipelines process all line items, GRN records, and exception flags using pandas-style operations. Replacing `import pandas` with `cudf.pandas` (zero code changes) produced:

- **6.8× speedup at 2M rows** in `cudf_benchmark.py`
- Enables full daily resync of multi-year invoice history in seconds rather than minutes
- Reconciliation results that would require an overnight batch are available interactively after each Drive sync

### Google BigQuery

- Live streaming insert on every sync keeps analytics current without ETL lag
- ITC aggregation (`itc_summary_bigquery.sql`) and vendor scoring (`vendor_score_bigquery.sql`) run across the full historical dataset at the DB layer - no rows pulled to the application server
- Scales to any invoice volume without schema changes

---

## Real-World Impact

| Metric | Before | After |
|--------|--------|-------|
| Time to detect a GRN quantity short | Days (manual) | Seconds (auto-flagged on sync) |
| ITC reconciliation with GSTR-2B | Weekly, manual | Automatic on each sync |
| Vendor grade visibility | None | Real-time A–F with drill-down |
| Cross-document exception detection | Never | 9 check types, every sync |
| Resync time for 2M row history | ~8 min (pandas) | ~70 sec (cuDF) |

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
```

### Database
Run migrations in order via Supabase SQL editor:
1. `schema.sql`
2. `migration_add_po_gstr2b_exceptions.sql`
3. `migration_add_training_exports.sql`
4. `migration_add_supply_chain.sql`

### Backend
```bash
pip install -r requirements.txt
python -m uvicorn app.main:app --reload --port 8000
```

### Frontend
```bash
cd webapp/frontend
npm install --legacy-peer-deps
npm run dev
```

### GPU Acceleration (optional)
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
│   ├── reconciliation.py     # Cross-document validation
│   ├── vendor_scorer.py      # A–F grading engine
│   └── gstr2b_parser.py      # GSTR-2B matching
├── scripts/
│   ├── bigquery_sync.py      # BQ live sync
│   └── cudf_benchmark.py     # GPU acceleration benchmark
├── sql/
│   ├── itc_summary_bigquery.sql
│   └── vendor_score_bigquery.sql
└── webapp/
    ├── backend/app/          # FastAPI application (35+ endpoints)
    └── frontend/src/         # React dashboard

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

## What's Next

- Mobile-responsive layout for on-the-go invoice approval
- Custom OCR specially trained on reading indian businesses documents accurately