"""
itc_engine.py — added 'excluded' confidence filtering

Change: rows where hsn_status = 'excluded' are dropped before any
computation. A blacklisted HSN code must never contribute claimable ITC
regardless of amount or business_use_percent.
"""

import logging

logger = logging.getLogger(__name__)

_GPU_AVAILABLE = False

try:
    import rmm
    rmm.reinitialize(
        pool_allocator=True,
        initial_pool_size=256 * 1024 * 1024,
        maximum_pool_size=2 * 1024 * 1024 * 1024,
    )
    import cudf.pandas
    cudf.pandas.install()
    _GPU_AVAILABLE = True
    logger.info("itc_engine: cudf.pandas GPU path active")
except Exception as _e:
    logger.info("itc_engine: cudf not available (%s), using CPU pandas", _e)

import pandas as pd  # noqa: E402


def compute_itc_summary(rows: list[dict]) -> dict:
    if not rows:
        return {
            "total_claimable_itc": 0.0,
            "line_items_counted": 0,
            "by_vendor": {},
            "by_hsn_status": {"expected": 0.0, "ambiguous": 0.0, "manual": 0.0,
                               "unknown": 0.0, "excluded": 0.0},
            "ambiguous_lines_needing_review": [],
            "excluded_lines": [],
            "accelerated": _GPU_AVAILABLE,
        }

    df = pd.DataFrame(rows)

    # ── Separate excluded lines BEFORE any ITC computation ─────────────────
    # Blacklisted HSN codes must never contribute claimable ITC.
    excluded_mask = df["hsn_status"] == "excluded"
    excluded_df = df[excluded_mask].copy()
    df = df[~excluded_mask].copy()

    for col in ("amount", "taxable_amount", "total_gst_amount",
                "business_use_percent", "line_tax_rate_percent"):
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df["biz_pct"] = df["business_use_percent"].fillna(100.0) / 100.0

    has_line_rate = df["line_tax_rate_percent"].notna()
    line_rate_tax = df["amount"] * df["line_tax_rate_percent"].fillna(0.0) / 100.0
    taxable_safe = df["taxable_amount"].replace(0.0, float("nan"))
    apportioned = df["total_gst_amount"] * (df["amount"] / taxable_safe)
    df["line_tax"] = line_rate_tax.where(has_line_rate, apportioned.fillna(0.0))
    df["claimable"] = df["line_tax"] * df["biz_pct"]

    total_claimable = float(df["claimable"].sum())
    line_count = int(len(df))

    by_vendor_series = df.groupby("vendor_name")["claimable"].sum().sort_values(ascending=False)
    by_vendor = {
        str(k): round(float(v), 2)
        for k, v in zip(by_vendor_series.index.to_list(), by_vendor_series.to_list())
    }

    valid_statuses = {"expected", "ambiguous", "manual", "unknown"}
    df["hsn_bucket"] = df["hsn_status"].where(
        df["hsn_status"].isin(list(valid_statuses)), other="unknown"
    )
    by_hsn_raw = df.groupby("hsn_bucket")["claimable"].sum()
    by_hsn_status = {"expected": 0.0, "ambiguous": 0.0, "manual": 0.0,
                     "unknown": 0.0, "excluded": 0.0}
    for bucket, val in zip(by_hsn_raw.index.to_list(), by_hsn_raw.to_list()):
        if bucket in by_hsn_status:
            by_hsn_status[bucket] = round(float(val), 2)

    ambiguous_mask = df["hsn_bucket"] == "ambiguous"
    if ambiguous_mask.any():
        ambig_df = df[ambiguous_mask][["invoice_id", "hsn_code", "claimable"]]
        ambiguous_lines = [
            {"invoice_id": str(r["invoice_id"]), "hsn_code": r["hsn_code"],
             "claimable": round(float(r["claimable"]), 2)}
            for r in ambig_df.to_dict("records")
        ]
    else:
        ambiguous_lines = []

    # Summary of excluded lines for the UI to show (informational only)
    excluded_lines = []
    if len(excluded_df) > 0:
        for r in excluded_df[["invoice_id", "hsn_code", "vendor_name"]].to_dict("records"):
            excluded_lines.append({
                "invoice_id": str(r.get("invoice_id", "")),
                "hsn_code": r.get("hsn_code", ""),
                "vendor_name": r.get("vendor_name", ""),
            })

    return {
        "total_claimable_itc": round(total_claimable, 2),
        "line_items_counted": line_count,
        "by_vendor": by_vendor,
        "by_hsn_status": by_hsn_status,
        "ambiguous_lines_needing_review": ambiguous_lines,
        "excluded_lines": excluded_lines,
        "accelerated": _GPU_AVAILABLE,
        "note": (
            "Claimable amount = line tax x business-use %. Excluded HSN codes "
            "(blacklisted) are never counted. Business-use % defaults to 100."
        ),
    }