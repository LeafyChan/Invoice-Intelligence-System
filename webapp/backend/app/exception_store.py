from sqlalchemy import text
from sqlalchemy.orm import Session


def insert_exceptions(db: Session, org_id: str, exceptions: list[dict]) -> int:
    count = 0
    for exc in exceptions:
        db.execute(
            text(
                "INSERT INTO exceptions "
                "(org_id, exception_type, severity, invoice_id, po_id, gstr2b_id, "
                " waybill_id, grn_id, mrn_id, vendor_id, description, detail, status) "
                "VALUES ("
                " CAST(:oid AS uuid), :etype, :severity,"
                " CAST(:iid AS uuid), CAST(:pid AS uuid), CAST(:gid AS uuid),"
                " CAST(:wid AS uuid), CAST(:grid AS uuid), CAST(:mid AS uuid),"
                " CAST(:vid AS uuid), :desc, CAST(:detail AS jsonb), :status"
                ")"
            ),
            {
                "oid":    org_id,
                "etype":  exc["exception_type"],
                "severity": exc.get("severity", "MEDIUM"),
                "iid":    exc.get("invoice_id"),
                "pid":    exc.get("po_id"),
                "gid":    exc.get("gstr2b_id"),
                "wid":    exc.get("waybill_id"),
                "grid":   exc.get("grn_id"),
                "mid":    exc.get("mrn_id"),
                "vid":    exc.get("vendor_id"),
                "desc":   exc.get("description", ""),
                "detail": _to_json(exc.get("detail")),
                "status": exc.get("status", "open"),
            }
        )
        count += 1
    return count


def _to_json(d):
    import json
    return json.dumps(d) if d is not None else None


def clear_stale_open_exceptions(
    db: Session, org_id: str, exception_type: str,
    still_valid_invoice_ids: set, still_valid_gstr2b_ids: set
) -> int:
    rows = db.execute(
        text(
            "SELECT exception_id, invoice_id, gstr2b_id FROM exceptions "
            "WHERE org_id = CAST(:oid AS uuid) AND exception_type = :etype AND status = 'open'"
        ),
        {"oid": org_id, "etype": exception_type}
    ).mappings().all()

    resolved = 0
    for r in rows:
        invoice_still_an_issue = (
            r["invoice_id"] and str(r["invoice_id"]) in still_valid_invoice_ids
        )
        gstr2b_still_an_issue = (
            r["gstr2b_id"] and str(r["gstr2b_id"]) in still_valid_gstr2b_ids
        )
        if not invoice_still_an_issue and not gstr2b_still_an_issue:
            db.execute(
                text(
                    "UPDATE exceptions SET status = 'resolved', resolved_at = now(), "
                    "resolution_note = 'Auto-resolved: condition no longer present on re-sync' "
                    "WHERE exception_id = :eid"
                ),
                {"eid": r["exception_id"]}
            )
            resolved += 1
    return resolved


def list_exceptions(
    db: Session, org_id: str, status: str = None,
    exception_type: str = None, page: int = 1, page_size: int = 50
) -> dict:
    filters = ["org_id = CAST(:oid AS uuid)"]
    params = {"oid": org_id}
    if status:
        filters.append("status = :status")
        params["status"] = status
    if exception_type:
        filters.append("exception_type = :etype")
        params["etype"] = exception_type
    where = "WHERE " + " AND ".join(filters)

    total = db.execute(
        text(f"SELECT COUNT(*) FROM exceptions {where}"), params
    ).scalar()
    params["limit"] = page_size
    params["offset"] = (page - 1) * page_size
    rows = db.execute(
        text(
            f"""SELECT exception_id, exception_type, severity, status,
                       invoice_id, po_id, gstr2b_id,
                       waybill_id, grn_id, mrn_id, vendor_id,
                       description, detail,
                       resolved_by, resolved_at, resolution_note, created_at
                FROM exceptions {where}
                ORDER BY created_at DESC
                LIMIT :limit OFFSET :offset"""
        ),
        params
    ).mappings().all()
    return {
        "total_count": total,
        "page": page,
        "page_size": page_size,
        "total_pages": max(1, -(-total // page_size)),
        "exceptions": [dict(r) for r in rows],
    }


def resolve_exception(
    db: Session, org_id: str, exception_id: str, user_id: str,
    status: str, resolution_note: str = None
) -> bool:
    """status must be 'resolved' or 'ignored'."""
    if status not in ("resolved", "ignored"):
        raise ValueError("status must be 'resolved' or 'ignored'")
    result = db.execute(
        text(
            "UPDATE exceptions SET status = :status, resolved_by = CAST(:uid AS uuid), "
            "resolved_at = now(), resolution_note = :note "
            "WHERE exception_id = CAST(:eid AS uuid) AND org_id = CAST(:oid AS uuid)"
        ),
        {
            "status": status, "uid": user_id, "note": resolution_note,
            "eid": exception_id, "oid": org_id,
        }
    )
    return result.rowcount > 0