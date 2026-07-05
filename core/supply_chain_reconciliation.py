"""
supply_chain_reconciliation.py
===============================
Cross-document validation for the 5-document supply chain (S17).

Chain: PO -> Invoice -> Waybill -> GRN -> Material Return

Raises the exception types defined in the project spec. Results are
returned as a list of exception dicts ready for exception_store.insert_exceptions().

Does NOT write to the DB directly — main.py's /reconciliation/run route
(or a dedicated /supply-chain/reconcile route added in S18) calls this
and passes the results to exception_store.insert_exceptions().
"""

from __future__ import annotations
from datetime import date, datetime, timedelta
from typing import Optional


def _today() -> date:
    return date.today()


def _parse_date(val) -> Optional[date]:
    if val is None:
        return None
    if isinstance(val, date):
        return val
    if isinstance(val, datetime):
        return val.date()
    try:
        return date.fromisoformat(str(val))
    except Exception:
        return None


def _exc(exception_type: str, severity: str, invoice_id=None, po_id=None,
         waybill_id=None, grn_id=None, mrn_id=None, vendor_id=None,
         description: str = "") -> dict:
    return {
        "exception_type": exception_type,
        "severity": severity,
        "invoice_id": str(invoice_id) if invoice_id else None,
        "po_id": str(po_id) if po_id else None,
        "waybill_id": str(waybill_id) if waybill_id else None,
        "grn_id": str(grn_id) if grn_id else None,
        "mrn_id": str(mrn_id) if mrn_id else None,
        "vendor_id": str(vendor_id) if vendor_id else None,
        "description": description,
        "status": "open",
    }


def run_supply_chain_reconciliation(
    invoices: list[dict],
    purchase_orders: list[dict],
    waybills: list[dict],
    grns: list[dict],
    material_returns: list[dict],
) -> list[dict]:
    """
    Runs all cross-document checks and returns a flat list of exception dicts.

    Callers pass lists of dicts (already fetched from DB, RLS already applied).
    All field names match the DB column names from migration_add_supply_chain.sql.
    """
    exceptions: list[dict] = []
    today = _today()

    # ── Index lookups ─────────────────────────────────────────────────────────
    # invoice_number -> invoice
    inv_by_number = {i["invoice_number"]: i for i in invoices if i.get("invoice_number")}
    # po_number -> po
    po_by_number = {p["po_number"]: p for p in purchase_orders if p.get("po_number")}
    # ewb_number -> waybill
    wb_by_ewb = {w["ewb_number"]: w for w in waybills if w.get("ewb_number")}
    # invoice_number -> first waybill covering it
    wb_by_invoice = {}
    for w in waybills:
        doc_no = w.get("document_number")
        if doc_no and doc_no not in wb_by_invoice:
            wb_by_invoice[doc_no] = w
    # grn_number -> grn
    grn_by_number = {g["grn_number"]: g for g in grns if g.get("grn_number")}

    # ── 1. waybill_invoice_mismatch ───────────────────────────────────────────
    for w in waybills:
        doc_no = w.get("document_number")
        if doc_no and doc_no not in inv_by_number:
            exceptions.append(_exc(
                "waybill_invoice_mismatch", "HIGH",
                waybill_id=w.get("waybill_id"),
                vendor_id=w.get("vendor_id"),
                description=f"Waybill {w.get('ewb_number')} references invoice "
                            f"'{doc_no}' which doesn't exist in books",
            ))

    # ── 2. transport_mode_mismatch ────────────────────────────────────────────
    for inv in invoices:
        po_no = inv.get("po_number")
        inv_no = inv.get("invoice_number")
        if not po_no or not inv_no:
            continue
        po = po_by_number.get(po_no)
        wb = wb_by_invoice.get(inv_no)
        if not po or not wb:
            continue
        requested = (po.get("requested_transport_mode") or "").strip().lower()
        actual = (wb.get("transport_mode_label") or "").strip().lower()
        if requested and actual and requested != actual:
            exceptions.append(_exc(
                "transport_mode_mismatch", "HIGH",
                invoice_id=inv.get("invoice_id"),
                po_id=po.get("po_id"),
                waybill_id=wb.get("waybill_id"),
                vendor_id=inv.get("vendor_id"),
                description=f"PO requested '{requested}' but waybill used '{actual}'",
            ))

    # ── 3. missing_waybill (invoice exists, no waybill within 7 days) ─────────
    for inv in invoices:
        inv_no = inv.get("invoice_number")
        if not inv_no:
            continue
        if inv_no not in wb_by_invoice:
            inv_date = _parse_date(inv.get("invoice_date"))
            if inv_date and (today - inv_date) > timedelta(days=7):
                exceptions.append(_exc(
                    "missing_waybill", "MEDIUM",
                    invoice_id=inv.get("invoice_id"),
                    vendor_id=inv.get("vendor_id"),
                    description=f"Invoice {inv_no} has no linked e-waybill after 7 days",
                ))

    # ── 4. missing_grn (waybill exists, no GRN within 14 days) ───────────────
    grn_waybill_numbers = {g.get("waybill_number") for g in grns if g.get("waybill_number")}
    for w in waybills:
        ewb = w.get("ewb_number")
        if ewb and ewb not in grn_waybill_numbers:
            ewb_date = _parse_date(w.get("ewb_date"))
            if ewb_date and (today - ewb_date) > timedelta(days=14):
                exceptions.append(_exc(
                    "missing_grn", "MEDIUM",
                    waybill_id=w.get("waybill_id"),
                    vendor_id=w.get("vendor_id"),
                    description=f"Waybill {ewb} has no GRN after 14 days",
                ))

    # ── 5. waybill_expired (ewb_valid_until < grn_date) ──────────────────────
    for g in grns:
        wb_no = g.get("waybill_number")
        if not wb_no:
            continue
        wb = wb_by_ewb.get(wb_no)
        if not wb:
            continue
        valid_until = _parse_date(wb.get("ewb_valid_until"))
        grn_date = _parse_date(g.get("grn_date"))
        if valid_until and grn_date and valid_until < grn_date:
            exceptions.append(_exc(
                "waybill_expired", "HIGH",
                waybill_id=wb.get("waybill_id"),
                grn_id=g.get("grn_id"),
                vendor_id=g.get("vendor_id"),
                description=f"Waybill {wb_no} expired {valid_until} but GRN received {grn_date}",
            ))

    # ── 6. grn_quantity_short / grn_quantity_over ─────────────────────────────
    for g in grns:
        ordered = g.get("total_quantity_ordered")
        received = g.get("total_quantity_received")
        if ordered and received and float(ordered) > 0:
            pct_diff = (float(received) - float(ordered)) / float(ordered) * 100
            if pct_diff < -2:
                exceptions.append(_exc(
                    "grn_quantity_short", "MEDIUM",
                    grn_id=g.get("grn_id"),
                    vendor_id=g.get("vendor_id"),
                    description=f"GRN {g.get('grn_number')}: received {received} vs ordered {ordered} "
                                f"({pct_diff:.1f}%)",
                ))
            elif pct_diff > 2:
                exceptions.append(_exc(
                    "grn_quantity_over", "MEDIUM",
                    grn_id=g.get("grn_id"),
                    vendor_id=g.get("vendor_id"),
                    description=f"GRN {g.get('grn_number')}: received {received} vs ordered {ordered} "
                                f"(+{pct_diff:.1f}%)",
                ))

    # ── 7. high_rejection_rate ────────────────────────────────────────────────
    for g in grns:
        rejection_pct = g.get("rejection_rate_pct")
        if rejection_pct is not None and float(rejection_pct) > 5:
            exceptions.append(_exc(
                "high_rejection_rate", "HIGH",
                grn_id=g.get("grn_id"),
                vendor_id=g.get("vendor_id"),
                description=f"GRN {g.get('grn_number')}: rejection rate {rejection_pct:.1f}%",
            ))

    # ── 8. material_returned ──────────────────────────────────────────────────
    for mr in material_returns:
        exceptions.append(_exc(
            "material_returned", "HIGH",
            mrn_id=mr.get("mrn_id"),
            grn_id=mr.get("grn_number"),   # string ref, not UUID — store resolves
            vendor_id=mr.get("vendor_id"),
            description=f"MRN {mr.get('mrn_number')}: {mr.get('return_reason')} — "
                        f"{mr.get('total_quantity_returned')} units returned",
        ))

    # ── 9. incoterm_insurance_gap ─────────────────────────────────────────────
    _buyer_risk_incoterms = {"EXW", "FCA", "FOB", "FAS"}
    for po in purchase_orders:
        incoterm = (po.get("incoterm") or "").upper()
        if incoterm in _buyer_risk_incoterms:
            # Flag if no insurance detail present (field TBD — use raw check for now)
            # This is LOW severity, so only flag once per PO
            exceptions.append(_exc(
                "incoterm_insurance_gap", "LOW",
                po_id=po.get("po_id"),
                vendor_id=po.get("vendor_id"),
                description=f"PO {po.get('po_number')}: incoterm {incoterm} puts transport "
                            f"risk on buyer — verify insurance is arranged",
            ))

    return exceptions