"""vendor_score_store.py — Upsert + retrieve vendor scores (Session 17)"""

from __future__ import annotations
import json
import sys
from pathlib import Path
from sqlalchemy import text
from .db import get_org_scoped_db

# Import scorer from core pipeline
sys.path.insert(0, str(Path(__file__).parents[4]))
from core.vendor_scorer import compute_vendor_score

def recalculate_and_store(org_id: str, vendor_id: str) -> dict:
    """Compute score and upsert into vendor_scores. Returns the score dict."""
    # compute_vendor_score needs a db connection — open one for the scorer,
    # then reuse the same session for the upsert so RLS stays set.
    with get_org_scoped_db(org_id) as db:
        result = compute_vendor_score(vendor_id=vendor_id, db=db, org_id=org_id)
        db.execute(text("""
            INSERT INTO vendor_scores (
                org_id, vendor_id, score, grade,
                quality_rate, on_time_rate, accuracy_rate,
                transport_compliance_rate, avg_advance_pct,
                total_invoices, total_grns, total_returns,
                flags, last_calculated_at
            ) VALUES (
                :org_id, CAST(:vendor_id AS UUID), :score, :grade,
                :quality_rate, :on_time_rate, :accuracy_rate,
                :transport_compliance_rate, :avg_advance_pct,
                :total_invoices, :total_grns, :total_returns,
                CAST(:flags AS JSONB), NOW()
            )
            ON CONFLICT (org_id, vendor_id) DO UPDATE SET
                score                     = EXCLUDED.score,
                grade                     = EXCLUDED.grade,
                quality_rate              = EXCLUDED.quality_rate,
                on_time_rate              = EXCLUDED.on_time_rate,
                accuracy_rate             = EXCLUDED.accuracy_rate,
                transport_compliance_rate = EXCLUDED.transport_compliance_rate,
                avg_advance_pct           = EXCLUDED.avg_advance_pct,
                total_invoices            = EXCLUDED.total_invoices,
                total_grns                = EXCLUDED.total_grns,
                total_returns             = EXCLUDED.total_returns,
                flags                     = EXCLUDED.flags,
                last_calculated_at        = NOW()
        """), {**result, "flags": json.dumps(result["flags"])})
    return result

def get_vendor_score(org_id: str, vendor_id: str) -> dict | None:
    with get_org_scoped_db(org_id) as db:
        row = db.execute(text("""
            SELECT vs.*, v.name AS vendor_name
            FROM vendor_scores vs
            JOIN vendors v ON v.vendor_id = vs.vendor_id
            WHERE vs.org_id = CAST(:org_id AS UUID)
              AND vs.vendor_id = CAST(:vendor_id AS UUID)
        """), {"org_id": org_id, "vendor_id": vendor_id}).fetchone()
    return dict(row._mapping) if row else None

def list_vendor_scorecards(org_id: str) -> list[dict]:
    with get_org_scoped_db(org_id) as db:
        rows = db.execute(text("""
            SELECT vs.vendor_id, v.name AS vendor_name,
                   vs.score, vs.grade, vs.quality_rate, vs.on_time_rate,
                   vs.accuracy_rate, vs.transport_compliance_rate,
                   vs.avg_advance_pct, vs.total_invoices, vs.total_grns,
                   vs.total_returns, vs.flags, vs.last_calculated_at
            FROM vendor_scores vs
            JOIN vendors v ON v.vendor_id = vs.vendor_id
            WHERE vs.org_id = CAST(:org_id AS UUID)
            ORDER BY vs.score DESC
        """), {"org_id": org_id}).fetchall()
    return [dict(r._mapping) for r in rows]