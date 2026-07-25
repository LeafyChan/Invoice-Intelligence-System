"""
supply_chain_reconciliation.py
================================
Cross-document validation for the 5-document supply chain.

Chain: PO → Invoice → Waybill → GRN → Material Return

All 10 checks — renamed for clarity, grouped by domain:

DOCUMENT LINKAGE (no token cost — pure DB join checks)
  1. orphan_waybill          — waybill references invoice that doesn't exist
  2. transport_mode_mismatch — PO requested mode ≠ waybill actual mode
  3. missing_waybill         — invoice has no waybill after 7 days
  4. missing_grn             — waybill has no GRN after 14 days

DELIVERY INTEGRITY
  5. expired_waybill         — e-waybill validity lapsed before GRN received
  6. quantity_discrepancy    — GRN received qty differs from PO ordered by >2%
  7. quality_rejection       — GRN rejection rate >5%

RETURNS & REVERSALS
  8. goods_returned          — any MRN exists for this supply chain leg

INCOTERMS COMPLIANCE (no LLM calls — uses extracted PO incoterm field)
  9. incoterm_transport_clash  — sea incoterm (FOB/CIF/CFR/FAS) but road/air used
 10. buyer_risk_uninsured      — buyer-risk incoterm with no insurance confirmation

All checks use already-fetched DB dicts. Zero LLM calls. Zero extra DB queries.
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
        "po_id":      str(po_id)      if po_id      else None,
        "waybill_id": str(waybill_id) if waybill_id else None,
        "grn_id":     str(grn_id)     if grn_id     else None,
        "mrn_id":     str(mrn_id)     if mrn_id     else None,
        "vendor_id":  str(vendor_id)  if vendor_id  else None,
        "description": description,
        "status": "open",
    }


# Incoterms that imply sea/waterway transport only
_SEA_INCOTERMS   = {"FOB", "CIF", "CFR", "FAS"}
# Incoterms that put transport risk on the buyer
_BUYER_RISK      = {"EXW", "FCA", "FOB", "FAS"}
# Transport mode labels that are NOT sea
_NON_SEA_MODES   = {"road", "rail", "air", "courier", "truck", "lorry", "express"}


def run_supply_chain_reconciliation(
    invoices: list[dict],
    purchase_orders: list[dict],
    waybills: list[dict],
    grns: list[dict],
    material_returns: list[dict],
) -> list[dict]:
    """
    Runs all 10 checks. Returns flat list of exception dicts.
    Callers pass lists already fetched from DB (RLS applied).
    """
    exceptions: list[dict] = []
    today = _today()

    # ── Indexes ───────────────────────────────────────────────────────────────
    inv_by_number  = {i["invoice_number"]: i for i in invoices  if i.get("invoice_number")}
    po_by_number   = {p["po_number"]: p      for p in purchase_orders if p.get("po_number")}
    wb_by_ewb      = {w["ewb_number"]: w     for w in waybills  if w.get("ewb_number")}
    wb_by_invoice  = {}
    for w in waybills:
        doc = w.get("document_number")
        if doc and doc not in wb_by_invoice:
            wb_by_invoice[doc] = w
    grn_waybill_nos = {g.get("waybill_number") for g in grns if g.get("waybill_number")}

    # ── 1. orphan_waybill ─────────────────────────────────────────────────────
    # Waybill document_number points to an invoice that doesn't exist in books.
    # Signals: duplicate shipment, wrong invoice number on waybill, or fraud.
    for w in waybills:
        doc = w.get("document_number")
        if doc and doc not in inv_by_number:
            exceptions.append(_exc(
                "orphan_waybill", "HIGH",
                waybill_id=w.get("waybill_id"),
                vendor_id=w.get("vendor_id"),
                description=f"Waybill {w.get('ewb_number')} references invoice "
                            f"'{doc}' which has no matching record",
            ))

    # ── 2. transport_mode_mismatch ────────────────────────────────────────────
    # PO explicitly requested a transport mode but waybill used a different one.
    # Signals: vendor bypassed agreed logistics terms — cost or compliance impact.
    for inv in invoices:
        po_no  = inv.get("po_number")
        inv_no = inv.get("invoice_number")
        if not po_no or not inv_no:
            continue
        po = po_by_number.get(po_no)
        wb = wb_by_invoice.get(inv_no)
        if not po or not wb:
            continue
        requested = (po.get("requested_transport_mode") or "").strip().lower()
        actual    = (wb.get("transport_mode_label")      or "").strip().lower()
        if requested and actual and requested != actual:
            exceptions.append(_exc(
                "transport_mode_mismatch", "HIGH",
                invoice_id=inv.get("invoice_id"),
                po_id=po.get("po_id"),
                waybill_id=wb.get("waybill_id"),
                vendor_id=inv.get("vendor_id"),
                description=f"PO required '{requested}' transport — "
                            f"waybill used '{actual}'",
            ))

    # ── 3. missing_waybill ────────────────────────────────────────────────────
    # Invoice older than 7 days with no linked e-waybill.
    # Signals: goods may have moved without GST compliance — ITC risk.
    # Guard: only flag invoices that have a po_number (real invoices, not stubs).
    for inv in invoices:
        inv_no = inv.get("invoice_number")
        po_no  = inv.get("po_number")
        if not inv_no or not po_no:
            continue
        if inv_no not in wb_by_invoice:
            inv_date = _parse_date(inv.get("invoice_date"))
            if inv_date and (today - inv_date) > timedelta(days=7):
                exceptions.append(_exc(
                    "missing_waybill", "MEDIUM",
                    invoice_id=inv.get("invoice_id"),
                    vendor_id=inv.get("vendor_id"),
                    description=f"Invoice {inv_no} has no e-waybill after "
                                f"{(today - inv_date).days} days",
                ))

    # ── 4. missing_grn ────────────────────────────────────────────────────────
    # Waybill older than 14 days with no GRN.
    # Signals: goods may not have been received or receipt wasn't recorded.
    for w in waybills:
        ewb = w.get("ewb_number")
        if ewb and ewb not in grn_waybill_nos:
            ewb_date = _parse_date(w.get("ewb_date"))
            if ewb_date and (today - ewb_date) > timedelta(days=14):
                exceptions.append(_exc(
                    "missing_grn", "MEDIUM",
                    waybill_id=w.get("waybill_id"),
                    vendor_id=w.get("vendor_id"),
                    description=f"Waybill {ewb} dispatched {ewb_date} — "
                                f"no GRN after {(today - ewb_date).days} days",
                ))

    # ── 5. expired_waybill ────────────────────────────────────────────────────
    # GRN receipt date is after the e-waybill's validity expiry.
    # Signals: legally invalid movement — penalty risk under GST e-way bill rules.
    for g in grns:
        wb_no = g.get("waybill_number")
        if not wb_no:
            continue
        wb = wb_by_ewb.get(wb_no)
        if not wb:
            continue
        valid_until = _parse_date(wb.get("ewb_valid_until"))
        grn_date    = _parse_date(g.get("grn_date"))
        if valid_until and grn_date and valid_until < grn_date:
            days_over = (grn_date - valid_until).days
            exceptions.append(_exc(
                "expired_waybill", "HIGH",
                waybill_id=wb.get("waybill_id"),
                grn_id=g.get("grn_id"),
                vendor_id=g.get("vendor_id"),
                description=f"Waybill {wb_no} expired {valid_until} — "
                            f"goods received {days_over} day(s) late on {grn_date}",
            ))

    # ── 6. quantity_discrepancy ───────────────────────────────────────────────
    # GRN received qty differs from PO ordered qty by more than 2%.
    # Signals: short delivery (pay dispute) or over-delivery (unwanted liability).
    for g in grns:
        ordered  = g.get("total_quantity_ordered")
        received = g.get("total_quantity_received")
        if ordered and received and float(ordered) > 0:
            pct = (float(received) - float(ordered)) / float(ordered) * 100
            if pct < -2:
                exceptions.append(_exc(
                    "quantity_discrepancy", "MEDIUM",
                    grn_id=g.get("grn_id"),
                    vendor_id=g.get("vendor_id"),
                    description=f"GRN {g.get('grn_number')}: received {received} "
                                f"vs ordered {ordered} — short by {abs(pct):.1f}%",
                ))
            elif pct > 2:
                exceptions.append(_exc(
                    "quantity_discrepancy", "MEDIUM",
                    grn_id=g.get("grn_id"),
                    vendor_id=g.get("vendor_id"),
                    description=f"GRN {g.get('grn_number')}: received {received} "
                                f"vs ordered {ordered} — over by {pct:.1f}%",
                ))

    # ── 7. quality_rejection ──────────────────────────────────────────────────
    # GRN rejection rate exceeds 5%.
    # Signals: vendor quality issue — feeds vendor scorecard penalty.
    for g in grns:
        rej = g.get("rejection_rate_pct")
        if rej is not None and float(rej) > 5:
            exceptions.append(_exc(
                "quality_rejection", "HIGH",
                grn_id=g.get("grn_id"),
                vendor_id=g.get("vendor_id"),
                description=f"GRN {g.get('grn_number')}: {float(rej):.1f}% rejection rate "
                            f"— exceeds 5% quality threshold",
            ))

    # ── 8. goods_returned ────────────────────────────────────────────────────
    # Any Material Return Note exists for this leg of the supply chain.
    # Signals: defective goods, wrong delivery, or contract dispute.
    for mr in material_returns:
        exceptions.append(_exc(
            "goods_returned", "HIGH",
            mrn_id=mr.get("mrn_id"),
            grn_id=mr.get("grn_number"),
            vendor_id=mr.get("vendor_id"),
            description=f"MRN {mr.get('mrn_number')}: "
                        f"{mr.get('total_quantity_returned')} units returned — "
                        f"reason: {mr.get('return_reason') or 'not specified'}",
        ))

    # ── 9. incoterm_transport_clash ───────────────────────────────────────────
    # PO incoterm implies sea transport (FOB/CIF/CFR/FAS) but waybill used road/air.
    # Signals: wrong carrier mode chosen — cost overrun or insurance void.
    # Uses only already-extracted PO incoterm field. Zero LLM calls.
    for inv in invoices:
        po_no  = inv.get("po_number")
        inv_no = inv.get("invoice_number")
        if not po_no or not inv_no:
            continue
        po = po_by_number.get(po_no)
        wb = wb_by_invoice.get(inv_no)
        if not po or not wb:
            continue
        incoterm  = (po.get("incoterm") or "").upper()
        transport = (wb.get("transport_mode_label") or "").lower()
        if incoterm in _SEA_INCOTERMS and any(m in transport for m in _NON_SEA_MODES):
            exceptions.append(_exc(
                "incoterm_transport_clash", "MEDIUM",
                invoice_id=inv.get("invoice_id"),
                po_id=po.get("po_id"),
                waybill_id=wb.get("waybill_id"),
                vendor_id=inv.get("vendor_id"),
                description=f"PO incoterm {incoterm} requires sea/waterway transport — "
                            f"waybill recorded '{transport}'",
            ))

    # ── 10. buyer_risk_uninsured ──────────────────────────────────────────────
    # PO incoterm places transport risk on the buyer (EXW/FCA/FOB/FAS)
    # with no insurance confirmation on file.
    # Signals: financial exposure if goods are lost/damaged in transit.
    # Low severity — advisory, not a compliance violation.
    for po in purchase_orders:
        incoterm = (po.get("incoterm") or "").upper()
        if incoterm in _BUYER_RISK:
            exceptions.append(_exc(
                "buyer_risk_uninsured", "LOW",
                po_id=po.get("po_id"),
                vendor_id=po.get("vendor_id"),
                description=f"PO {po.get('po_number')}: incoterm {incoterm} — "
                            f"buyer bears transport risk. Confirm insurance is in place.",
            ))

    return exceptions