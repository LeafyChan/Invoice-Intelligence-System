"""vendor_scorer.py — Vendor grading engine (Session 17)

All DB calls use SQLAlchemy text() so the same org-scoped Session from
the route is passed straight through — no second connection opened.
"""
from __future__ import annotations
from datetime import datetime, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

GRADE_BANDS = [(85, "A"), (70, "B"), (55, "C"), (40, "D"), (0, "F")]


def _grade(score: float) -> str:
    for threshold, grade in GRADE_BANDS:
        if score >= threshold:
            return grade
    return "F"


def compute_vendor_score(vendor_id: str, db: Session, org_id: str) -> dict:
    now = datetime.utcnow()
    cutoff_90 = (now - timedelta(days=90)).date().isoformat()
    p = {"org": org_id, "vid": vendor_id}

    # ── Quality rate ─────────────────────────────────────────
    grn_row = db.execute(text("""
        SELECT COALESCE(SUM(total_quantity_received), 0) AS total_recv,
               COALESCE(SUM(total_quantity_rejected),  0) AS total_rej
        FROM grn
        WHERE org_id = CAST(:org AS UUID) AND vendor_id = CAST(:vid AS UUID)
    """), p).mappings().fetchone()

    total_recv = float(grn_row["total_recv"] or 0)

    ret_row = db.execute(text("""
        SELECT COALESCE(SUM(total_quantity_returned), 0) AS total_ret
        FROM material_returns
        WHERE org_id = CAST(:org AS UUID) AND vendor_id = CAST(:vid AS UUID)
    """), p).mappings().fetchone()

    total_returned = float(ret_row["total_ret"] or 0)
    quality_rate = max(0.0, min(1.0, (1 - total_returned / total_recv) if total_recv > 0 else 1.0))

    # ── On-time delivery ─────────────────────────────────────
    ot_row = db.execute(text("""
        SELECT COUNT(*) FILTER (WHERE i.invoice_date <= po.delivery_date_requested) AS on_time,
               COUNT(*) AS total
        FROM invoices i
        JOIN purchase_orders po ON po.po_number = i.po_number
        WHERE i.org_id    = CAST(:org AS UUID)
          AND i.vendor_id = CAST(:vid AS UUID)
          AND po.delivery_date_requested IS NOT NULL
    """), p).mappings().fetchone()

    on_time_rate = (float(ot_row["on_time"]) / float(ot_row["total"])) if ot_row["total"] else 1.0

    # ── Invoice accuracy ─────────────────────────────────────
    acc_row = db.execute(text("""
        SELECT COUNT(*) FILTER (WHERE status NOT IN ('WARNING', 'FAILED')) AS clean,
               COUNT(*) AS total
        FROM invoices
        WHERE org_id    = CAST(:org AS UUID)
          AND vendor_id = CAST(:vid AS UUID)
    """), p).mappings().fetchone()

    accuracy_rate  = (float(acc_row["clean"]) / float(acc_row["total"])) if acc_row["total"] else 1.0
    total_invoices = int(acc_row["total"] or 0)

    # ── Transport compliance ──────────────────────────────────
    tc_row = db.execute(text("""
        SELECT COUNT(*) FILTER (
                   WHERE LOWER(po.requested_transport_mode) = LOWER(w.transport_mode_label)
               ) AS compliant,
               COUNT(*) FILTER (WHERE po.requested_transport_mode IS NOT NULL) AS total
        FROM waybills w
        JOIN invoices i        ON i.invoice_number = w.document_number
                              AND i.org_id = CAST(:org AS UUID)
        JOIN purchase_orders po ON po.po_number = i.po_number
                              AND po.org_id = CAST(:org AS UUID)
        WHERE w.org_id    = CAST(:org AS UUID)
          AND w.vendor_id = CAST(:vid AS UUID)
    """), p).mappings().fetchone()

    transport_compliance_rate = (
        float(tc_row["compliant"]) / float(tc_row["total"])
        if tc_row["total"] else 1.0
    )

    # ── Average advance % ────────────────────────────────────
    adv_row = db.execute(text("""
        SELECT COALESCE(AVG(advance_payment_percent), 0) AS avg_adv
        FROM purchase_orders
        WHERE org_id    = CAST(:org AS UUID)
          AND vendor_id = CAST(:vid AS UUID)
          AND advance_payment_percent IS NOT NULL
    """), p).mappings().fetchone()

    avg_advance_pct = float(adv_row["avg_adv"] or 0)

    # ── Counts ───────────────────────────────────────────────
    total_grns = db.execute(text("""
        SELECT COUNT(*) AS c FROM grn
        WHERE org_id = CAST(:org AS UUID) AND vendor_id = CAST(:vid AS UUID)
    """), p).mappings().fetchone()["c"]

    total_returns = db.execute(text("""
        SELECT COUNT(*) AS c FROM material_returns
        WHERE org_id = CAST(:org AS UUID) AND vendor_id = CAST(:vid AS UUID)
    """), p).mappings().fetchone()["c"]

    # ── Weighted score ───────────────────────────────────────
    weighted = (
        quality_rate              * 0.35 +
        on_time_rate              * 0.20 +
        accuracy_rate             * 0.20 +
        transport_compliance_rate * 0.15
    ) * 100 - (avg_advance_pct * 0.10)
    weighted = max(0.0, min(100.0, weighted))
    grade    = _grade(weighted)

    # ── Override flags ───────────────────────────────────────
    flags: list[str] = []

    rejection_recent = db.execute(text("""
        SELECT COUNT(*) AS c FROM grn
        WHERE org_id    = CAST(:org AS UUID)
          AND vendor_id = CAST(:vid AS UUID)
          AND rejection_rate_pct > 5
          AND grn_date >= CAST(:cutoff AS DATE)
    """), {**p, "cutoff": cutoff_90}).mappings().fetchone()["c"]

    if rejection_recent > 0:
        flags.append("high_rejection_rate")
        if grade in ("A", "B"):
            grade = "C"

    if avg_advance_pct > 50 and grade not in ("A", "B"):
        flags.append("advance_risk")

    transport_mismatches = db.execute(text("""
        SELECT COUNT(*) AS c FROM exceptions
        WHERE org_id    = CAST(:org AS UUID)
          AND vendor_id = CAST(:vid AS UUID)
          AND exception_type = 'transport_mode_mismatch'
    """), p).mappings().fetchone()["c"]

    if transport_mismatches >= 2:
        flags.append("logistics_non_compliant")

    waybill_expired = db.execute(text("""
        SELECT COUNT(*) AS c FROM exceptions
        WHERE org_id    = CAST(:org AS UUID)
          AND vendor_id = CAST(:vid AS UUID)
          AND exception_type = 'waybill_expired'
    """), p).mappings().fetchone()["c"]

    if waybill_expired > 0:
        flags.append("compliance_risk")

    return {
        "org_id":                    org_id,
        "vendor_id":                 vendor_id,
        "score":                     round(weighted, 2),
        "grade":                     grade,
        "quality_rate":              round(quality_rate, 4),
        "on_time_rate":              round(on_time_rate, 4),
        "accuracy_rate":             round(accuracy_rate, 4),
        "transport_compliance_rate": round(transport_compliance_rate, 4),
        "avg_advance_pct":           round(avg_advance_pct, 2),
        "total_invoices":            total_invoices,
        "total_grns":                int(total_grns or 0),
        "total_returns":             int(total_returns or 0),
        "flags":                     flags,
        "last_calculated_at":        now.isoformat(),
    }