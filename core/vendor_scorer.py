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
    vrow = db.execute(text("""
        SELECT vendor_gstin FROM vendors
        WHERE org_id = CAST(:org AS UUID) AND vendor_id = CAST(:vid AS UUID)
    """), {"org": org_id, "vid": vendor_id}).mappings().fetchone()

    if not vrow or not vrow["vendor_gstin"]:
        gstin = None
    else:
        gstin = vrow["vendor_gstin"]

    p = {"org": org_id, "gstin": gstin}

    if not gstin:
        return {
            "org_id": org_id, "vendor_id": vendor_id,
            "score": 50.0, "grade": "C",
            "quality_rate": 1.0, "on_time_rate": 1.0,
            "accuracy_rate": 1.0, "transport_compliance_rate": 1.0,
            "avg_advance_pct": 0.0,
            "total_invoices": 0, "total_grns": 0, "total_returns": 0,
            "flags": {},
        }
    grn_row = db.execute(text("""
        SELECT COALESCE(SUM(total_quantity_received), 0) AS total_recv
        FROM grn
        WHERE org_id = CAST(:org AS UUID) AND vendor_gstin = :gstin
    """), p).mappings().fetchone()
    total_recv = float(grn_row["total_recv"] or 0)

    ret_row = db.execute(text("""
        SELECT COALESCE(SUM(total_quantity_returned), 0) AS total_ret
        FROM material_returns
        WHERE org_id = CAST(:org AS UUID) AND vendor_gstin = :gstin
    """), p).mappings().fetchone()
    total_returned = float(ret_row["total_ret"] or 0)
    total_grns = db.execute(text(
        "SELECT COUNT(*) FROM grn WHERE org_id = CAST(:org AS UUID) AND vendor_gstin = :gstin"
    ), p).scalar() or 0
    total_returns = db.execute(text(
        "SELECT COUNT(*) FROM material_returns WHERE org_id = CAST(:org AS UUID) AND vendor_gstin = :gstin"
    ), p).scalar() or 0

    quality_rate = max(0.0, min(1.0, (1 - total_returned / total_recv) if total_recv > 0 else 1.0))
    ot_row = db.execute(text("""
        SELECT COUNT(*) FILTER (WHERE i.invoice_date <= po.delivery_date_requested) AS on_time,
               COUNT(*) AS total
        FROM invoices i
        JOIN purchase_orders po ON po.po_number = i.po_number AND po.org_id = i.org_id
        WHERE i.org_id = CAST(:org AS UUID)
          AND i.vendor_gstin = :gstin
          AND po.delivery_date_requested IS NOT NULL
    """), p).mappings().fetchone()
    on_time_rate = (float(ot_row["on_time"]) / float(ot_row["total"])) if ot_row["total"] else 1.0
    acc_row = db.execute(text("""
        SELECT COUNT(*) FILTER (WHERE status NOT IN ('WARNING','FAILED')) AS clean,
               COUNT(*) AS total
        FROM invoices
        WHERE org_id = CAST(:org AS UUID) AND vendor_gstin = :gstin
    """), p).mappings().fetchone()
    accuracy_rate  = (float(acc_row["clean"]) / float(acc_row["total"])) if acc_row["total"] else 1.0
    total_invoices = int(acc_row["total"] or 0)
    tc_row = db.execute(text("""
        SELECT COUNT(*) FILTER (
                   WHERE LOWER(po.requested_transport_mode) = LOWER(w.transport_mode_label)
               ) AS compliant,
               COUNT(*) FILTER (WHERE po.requested_transport_mode IS NOT NULL) AS total
        FROM waybills w
        JOIN invoices i ON i.invoice_number = w.document_number AND i.org_id = CAST(:org AS UUID)
        JOIN purchase_orders po ON po.po_number = i.po_number AND po.org_id = i.org_id
        WHERE i.vendor_gstin = :gstin
    """), p).mappings().fetchone()
    transport_compliance_rate = (float(tc_row["compliant"]) / float(tc_row["total"])) if tc_row["total"] else 1.0
    adv_row = db.execute(text("""
        SELECT COALESCE(AVG(advance_payment_percent), 0) AS avg_adv
        FROM purchase_orders
        WHERE org_id = CAST(:org AS UUID)
          AND vendor_gstin = :gstin
          AND advance_payment_percent IS NOT NULL
    """), p).mappings().fetchone()
    avg_advance_pct = float(adv_row["avg_adv"] or 0)
    score = (
        quality_rate              * 35 +
        on_time_rate              * 20 +
        accuracy_rate             * 20 +
        transport_compliance_rate * 15 +
        max(0, 1 - avg_advance_pct / 100) * 10
    )
    flags = {}
    rej_90 = db.execute(text("""
        SELECT COALESCE(SUM(total_quantity_received),0) AS recv,
               COALESCE(SUM(total_quantity_rejected),0)  AS rej
        FROM grn
        WHERE org_id = CAST(:org AS UUID) AND vendor_gstin = :gstin
          AND grn_date >= :cutoff
    """), {**p, "cutoff": cutoff_90}).mappings().fetchone()
    recv_90 = float(rej_90["recv"] or 0)
    rej_90_val = float(rej_90["rej"] or 0)
    if recv_90 > 0 and (rej_90_val / recv_90) > 0.05:
        flags["high_rejection_rate"] = True
        score = min(score, 54)

    if avg_advance_pct > 50 and score < 70:
        flags["advance_risk"] = True

    grade = _grade(score)
    return {
        "org_id": org_id, "vendor_id": vendor_id,
        "score": round(score, 2), "grade": grade,
        "quality_rate": quality_rate, "on_time_rate": on_time_rate,
        "accuracy_rate": accuracy_rate,
        "transport_compliance_rate": transport_compliance_rate,
        "avg_advance_pct": avg_advance_pct,
        "total_invoices": total_invoices,
        "total_grns": int(total_grns),
        "total_returns": int(total_returns),
        "flags": flags,
    }