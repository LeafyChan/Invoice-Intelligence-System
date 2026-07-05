"""
itc_engine.py
=============
GPU-accelerated ITC apportionment — the same math as main.py's
/itc-summary Python loop, vectorized with cudf.pandas (GPU) where
available, falling back to regular pandas on CPU with zero code change.

HOW THE IMPORT SWAP WORKS:
  cudf.pandas.install() monkey-patches the `pandas` module so that
  `import pandas as pd` after that call returns the GPU-backed version.
  We isolate this to this module so the rest of the app is unaffected.
  If cudf isn't installed (dev laptop, CPU-only server), the try/except
  falls back to regular pandas — same results, no GPU speedup, no crash.

WHY THIS MODULE EXISTS INSTEAD OF PATCHING main.py INLINE:
  The /itc-summary route currently iterates rows in a Python for loop.
  Replacing that with a DataFrame groupby is already a vectorization win
  on CPU (pandas is faster than a Python loop over 10k+ rows). The GPU
  path is an additional multiplier on top of that. Keeping it in a
  separate module also makes it independently testable.

CALLED FROM:
  main.py's GET /itc-summary route — drop-in replacement for the loop.
  Also used by the /analytics/itc-summary-fast route for explicit GPU
  timing/comparison evidence.
"""

import logging

logger = logging.getLogger(__name__)

_GPU_AVAILABLE = False

try:
    import rmm
    rmm.reinitialize(
        pool_allocator=True,
        initial_pool_size=256 * 1024 * 1024,       # 256 MB initial
        maximum_pool_size=2 * 1024 * 1024 * 1024,  # 2 GB max — safe for RTX 4050
    )
    import cudf.pandas
    cudf.pandas.install()
    _GPU_AVAILABLE = True
    logger.info("itc_engine: cudf.pandas GPU path active")
except Exception as _e:
    logger.info("itc_engine: cudf not available (%s), using CPU pandas", _e)

import pandas as pd  # noqa: E402 — either cudf.pandas or plain pandas depending on above


def compute_itc_summary(rows: list[dict]) -> dict:
    """
    rows: list of dicts as returned by the /itc-summary Postgres query —
      keys: invoice_id, vendor_name, hsn_code, hsn_status, amount,
            taxable_amount, total_gst_amount, business_use_percent,
            line_tax_rate_percent.

    Returns the same shape as main.py's old Python-loop implementation so
    it's a drop-in swap with no frontend changes needed.
    """
    if not rows:
        return {
            "total_claimable_itc": 0.0,
            "line_items_counted": 0,
            "by_vendor": {},
            "by_hsn_status": {"expected": 0.0, "ambiguous": 0.0, "manual": 0.0, "unknown": 0.0},
            "ambiguous_lines_needing_review": [],
            "accelerated": _GPU_AVAILABLE,
        }

    df = pd.DataFrame(rows)

    # Cast to float — Postgres Decimal columns come through as strings or
    # Decimal objects; pandas/cudf both handle float64 natively.
    for col in ("amount", "taxable_amount", "total_gst_amount",
                "business_use_percent", "line_tax_rate_percent"):
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df["biz_pct"] = df["business_use_percent"].fillna(100.0) / 100.0

    # ITC per line: use per-line tax rate when present, else apportion
    # total invoice GST proportionally by line amount / taxable total.
    has_line_rate = df["line_tax_rate_percent"].notna()
    line_rate_tax = df["amount"] * df["line_tax_rate_percent"].fillna(0.0) / 100.0
    taxable_safe = df["taxable_amount"].replace(0.0, float("nan"))
    apportioned = df["total_gst_amount"] * (df["amount"] / taxable_safe)
    df["line_tax"] = line_rate_tax.where(has_line_rate, apportioned.fillna(0.0))
    df["claimable"] = df["line_tax"] * df["biz_pct"]

    total_claimable = float(df["claimable"].sum())
    line_count = int(len(df))

    # by_vendor — sorted descending by claimable ITC
    by_vendor_series = df.groupby("vendor_name")["claimable"].sum().sort_values(ascending=False)
    by_vendor = {
        str(k): round(float(v), 2)
        for k, v in zip(by_vendor_series.index.to_list(), by_vendor_series.to_list())
    }

    # by_hsn_status — fixed buckets
    valid_statuses = {"expected", "ambiguous", "manual", "unknown"}
    df["hsn_bucket"] = df["hsn_status"].where(
        df["hsn_status"].isin(list(valid_statuses)), other="unknown"
    )
    by_hsn_raw = df.groupby("hsn_bucket")["claimable"].sum()
    by_hsn_status = {"expected": 0.0, "ambiguous": 0.0, "manual": 0.0, "unknown": 0.0}
    for bucket, val in zip(by_hsn_raw.index.to_list(), by_hsn_raw.to_list()):
        if bucket in by_hsn_status:
            by_hsn_status[bucket] = round(float(val), 2)

    # ambiguous lines needing review — need invoice_id back
    ambiguous_mask = df["hsn_bucket"] == "ambiguous"
    if ambiguous_mask.any():
        ambig_df = df[ambiguous_mask][["invoice_id", "hsn_code", "claimable"]]
        ambiguous_lines = [
            {
                "invoice_id": str(row["invoice_id"]),
                "hsn_code": row["hsn_code"],
                "claimable": round(float(row["claimable"]), 2),
            }
            for row in ambig_df.to_dict("records")
        ]
    else:
        ambiguous_lines = []

    return {
        "total_claimable_itc": round(total_claimable, 2),
        "line_items_counted": line_count,
        "by_vendor": by_vendor,
        "by_hsn_status": by_hsn_status,
        "ambiguous_lines_needing_review": ambiguous_lines,
        "accelerated": _GPU_AVAILABLE,
        "note": (
            "Claimable amount = line tax x business-use %. Business-use % "
            "defaults to 100 and must be edited per line for any item with "
            "a personal/mixed-use portion (e.g. partial-quantity purchases) "
            "- this total does not itself know which lines need that edit."
        ),
    }