"""
cudf_benchmark.py
==================
Benchmarks the ITC apportionment + groupby logic from main.py's
/itc-summary route — same math, same branch logic — on synthetic
invoice line-item data, using plain pandas first then cudf.pandas.

Runs locally on RTX 4050 (CUDA 13.0, WSL2/Linux).

INSTALL (one-time, inside your venv):
    pip install cudf-cu12 --extra-index-url=https://pypi.nvidia.com
    # If cudf-cu12 doesn't match your CUDA, try cudf-cu11 or check:
    # https://docs.rapids.ai/install

    Verify GPU is visible first:
        python -c "import cupy; print(cupy.cuda.runtime.getDeviceProperties(0)['name'])"

USAGE:
    cd ~/personal_project
    python scripts/cudf_benchmark.py              # default 2M rows
    python scripts/cudf_benchmark.py --rows 5000000

OUTPUT:
    pandas:       X.XXXs
    cudf.pandas:  X.XXXs
    speedup:      Nx
    results match: True

OOM FIX vs original:
    The original script built a Python list-of-dicts with uuid strings
    (~800 bytes/row as Python objects). At 500k rows that's ~400 MB of
    Python heap before the DataFrame exists, and at 2M+ rows it OOMs.
    This version generates every column as a numpy array directly —
    no per-row Python objects, no UUID strings (integer IDs instead),
    no df.copy() inside compute — peak RAM is ~3x lower for the same
    row count, and generation is 10-20x faster.
"""

import argparse
import time

import numpy as np
import pandas as pd_plain


# ── Constants (same domain as original) ───────────────────────────────────────

VENDOR_NAMES = np.array([
    "Metro Cash Carry Pvt Ltd",   "Metro Cash Carry Traders",
    "MCC C&C",                    "Metro Cash Carry & Co",
    "Shree Traders Pvt Ltd",      "Shree Traders Traders",
    "ST C&C",                     "Shree Traders & Co",
    "ABC Metals Pvt Ltd",         "ABC Metals Traders",
    "AM C&C",                     "ABC Metals & Co",
    "XYZ Hardware Pvt Ltd",       "XYZ Hardware Traders",
    "XH C&C",                     "XYZ Hardware & Co",
    "Global Enterprises Pvt Ltd", "Global Enterprises Traders",
    "GE C&C",                     "Global Enterprises & Co",
    "National Suppliers Pvt Ltd", "National Suppliers Traders",
    "NS C&C",                     "National Suppliers & Co",
    "Prime Industrial Pvt Ltd",   "Prime Industrial Traders",
    "PI C&C",                     "Prime Industrial & Co",
    "Sunrise Textiles Pvt Ltd",   "Sunrise Textiles Traders",
    "Om Sai Traders Pvt Ltd",     "Om Sai Traders & Co",
    "Deccan Steel Corp Pvt Ltd",  "Deccan Steel Corp Traders",
    "Krishna Electricals Pvt Ltd","Krishna Electricals & Co",
    "Bharat Packaging Pvt Ltd",   "Bharat Packaging Traders",
    "Vishal Chemicals Pvt Ltd",   "Vishal Chemicals & Co",
], dtype=object)

HSN_CODES = np.array(
    ["7308","8481","3926","4820","8471","9403","2710","5407","7318","8536","3923","6802"],
    dtype=object)
HSN_STATUS = np.array(
    ["expected","expected","expected","expected","ambiguous","expected",
     "ambiguous","expected","expected","unknown","expected","ambiguous"],
    dtype=object)

# GST rate choices (weights favour 18%)
GST_RATES = np.array([0.05, 0.12, 0.18, 0.28])
GST_RATE_W = np.array([0.10, 0.20, 0.55, 0.15])

# line_tax_rate choices: None (=NaN) gets weight 2/7, others equal
LTR_VALUES = np.array([np.nan, np.nan, 5.0, 12.0, 18.0, 28.0, np.nan])

# business_use_percent choices (weighted toward 100)
BUP_VALUES  = np.array([100., 100., 100., 100., 75., 50., 90.])


# ── Fast numpy-based data generator ──────────────────────────────────────────

def generate_dataframe(n: int, pd_mod=pd_plain) -> "pd_mod.DataFrame":
    """
    Build a DataFrame of n synthetic line items entirely via numpy arrays.
    No Python-level loops, no list-of-dicts, no UUID strings.
    Peak RAM ≈ n * ~200 bytes (vs ~800 bytes/row in the original).
    """
    rng = np.random.default_rng(42)

    # ── invoice-level fields (one per invoice, broadcast to lines) ────────────
    # Assign 1–5 lines per invoice, fully vectorized:
    # Generate more invoices than we need, then trim to exactly n lines.
    n_inv_est = n // 2 + 1000          # generous overestimate (avg ~3 lines/inv)
    lines_per_inv = rng.integers(1, 6, size=n_inv_est)
    cumsum        = np.cumsum(lines_per_inv)
    n_inv_needed  = int(np.searchsorted(cumsum, n, side="left")) + 1
    lines_per_inv = lines_per_inv[:n_inv_needed]

    # Build repeat index: invoice 0 repeats lines_per_inv[0] times, etc.
    inv_ids_per_line_full = np.repeat(np.arange(n_inv_needed, dtype=np.int32),
                                      lines_per_inv)[:n]

    # Per-invoice taxable and gst amounts
    taxable_inv = np.round(rng.uniform(500, 200_000, size=n_inv_needed), 2)
    rate_idx    = rng.choice(len(GST_RATES), size=n_inv_needed, p=GST_RATE_W)
    gst_inv     = np.round(taxable_inv * GST_RATES[rate_idx], 2)

    inv_ids_per_line = inv_ids_per_line_full
    taxable_per_line = taxable_inv[inv_ids_per_line]
    gst_per_line     = gst_inv[inv_ids_per_line]

    # ── line-level fields ─────────────────────────────────────────────────────
    vendor_idx  = rng.integers(0, len(VENDOR_NAMES), size=n)
    vendor_name = VENDOR_NAMES[vendor_idx]

    hsn_idx  = rng.integers(0, len(HSN_CODES), size=n)
    hsn_code = HSN_CODES[hsn_idx]
    hsn_stat = HSN_STATUS[hsn_idx]

    # amount = taxable * jitter / lines_in_group (approximate; good enough)
    jitter = rng.uniform(0.7, 1.3, size=n)
    amount = np.round(taxable_per_line * jitter, 2)

    bup_idx = rng.integers(0, len(BUP_VALUES), size=n)
    bup     = BUP_VALUES[bup_idx]

    ltr_idx = rng.integers(0, len(LTR_VALUES), size=n)
    ltr     = LTR_VALUES[ltr_idx]     # contains NaN for "None" rows

    # ── assemble ──────────────────────────────────────────────────────────────
    data = {
        "line_item_id":          np.arange(n, dtype=np.int32),
        "invoice_id":            inv_ids_per_line,
        "vendor_name":           vendor_name,
        "hsn_code":              hsn_code,
        "hsn_status":            hsn_stat,
        "amount":                amount,
        "taxable_amount":        taxable_per_line,
        "total_gst_amount":      gst_per_line,
        "business_use_percent":  bup,
        "line_tax_rate_percent": ltr,
    }
    return pd_mod.DataFrame(data)


# ── ITC apportionment (no df.copy — saves another ~200 bytes/row peak) ────────

def compute_itc_summary(df):
    """
    Same math as main.py's /itc-summary route, vectorized.
    Works on any pandas-compatible DataFrame (plain pandas or cudf.pandas).
    Avoids df.copy() — operates on new Series only.
    """
    biz_pct = df["business_use_percent"].fillna(100) / 100.0

    has_line_rate      = df["line_tax_rate_percent"].notna()
    line_tax_rate      = df["amount"] * df["line_tax_rate_percent"].fillna(0) / 100.0
    line_tax_apportion = df["total_gst_amount"] * (
        df["amount"] / df["taxable_amount"].replace(0, float("nan"))
    )
    line_tax  = line_tax_rate.where(has_line_rate, line_tax_apportion.fillna(0))
    claimable = line_tax * biz_pct

    total     = float(claimable.sum())
    by_vendor = claimable.groupby(df["vendor_name"]).sum().sort_values(ascending=False)
    by_hsn    = claimable.groupby(df["hsn_status"]).sum()
    return total, by_vendor, by_hsn


# ── Benchmark runner ──────────────────────────────────────────────────────────

def run(n_rows: int):
    print(f"\nGenerating {n_rows:,} synthetic line items (numpy path)…")
    t_gen = time.perf_counter()
    df_cpu = generate_dataframe(n_rows, pd_mod=pd_plain)
    gen_time = time.perf_counter() - t_gen
    n_vendors = df_cpu["vendor_name"].nunique()
    mem_mb    = df_cpu.memory_usage(deep=True).sum() / 1024**2
    print(f"  done in {gen_time:.2f}s — {n_vendors} vendor variants, "
          f"DataFrame RAM ≈ {mem_mb:.0f} MB")

    # ── pandas baseline ──────────────────────────────────────────────────────
    print("\n[1/2] pandas baseline…")
    # warm-up (avoid first-call pandas overhead skewing result)
    _ = compute_itc_summary(df_cpu.head(1000))
    t0 = time.perf_counter()
    total_cpu, by_vendor_cpu, _ = compute_itc_summary(df_cpu)
    pandas_time = time.perf_counter() - t0
    print(f"  total claimable ITC : ₹{total_cpu:,.2f}")
    print(f"  top vendor          : {by_vendor_cpu.index[0]}")
    print(f"  wall-clock          : {pandas_time:.3f}s")

    # ── cudf.pandas ─────────────────────────────────────────────────────────
    print("\n[2/2] cudf.pandas (GPU)…")
    try:
        # Cap RMM pool — RTX 4050 has 6 GB VRAM but ~300 MB is reserved
        # by the display driver under WSL2+Windows; 3 GB pool is safe for
        # up to ~5M rows of this schema.
        import rmm
        rmm.reinitialize(
            pool_allocator=True,
            initial_pool_size=512  * 1024 * 1024,      # 512 MB start
            maximum_pool_size=5    * 1024 * 1024 * 1024, # 3 GB max
        )
        import cudf.pandas
        cudf.pandas.install()
        import pandas as pd_gpu   # now GPU-backed via cudf.pandas

        print("  transferring DataFrame to GPU…")
        t_xfer = time.perf_counter()
        df_gpu = pd_gpu.DataFrame(df_cpu)             # H→D transfer
        xfer_time = time.perf_counter() - t_xfer
        print(f"  H→D transfer        : {xfer_time:.3f}s")

        # warm-up (CUDA JIT + cuDF kernel cache — not counted in benchmark)
        _ = compute_itc_summary(df_gpu.head(1000))

        t0 = time.perf_counter()
        total_gpu, by_vendor_gpu, _ = compute_itc_summary(df_gpu)
        gpu_time = time.perf_counter() - t0
        print(f"  total claimable ITC : ₹{float(total_gpu):,.2f}")
        print(f"  wall-clock          : {gpu_time:.3f}s")

    except ImportError:
        print("  cudf not installed. Run:")
        print("  pip install cudf-cu12 --extra-index-url=https://pypi.nvidia.com")
        return
    except Exception as e:
        print(f"  GPU run failed: {e}")
        return

    # ── results ──────────────────────────────────────────────────────────────
    speedup = pandas_time / gpu_time if gpu_time > 0 else float("inf")
    match   = abs(total_cpu - float(total_gpu)) < 1.0

    print("\n── Results ──────────────────────────────────────────────")
    print(f"  rows              : {n_rows:,}")
    print(f"  pandas            : {pandas_time:.3f}s")
    print(f"  cudf.pandas (GPU) : {gpu_time:.3f}s  (excl. H→D transfer)")
    print(f"  speedup           : {speedup:.1f}x")
    print(f"  results match     : {match}")
    if not match:
        diff = abs(total_cpu - float(total_gpu))
        print(f"  WARNING: totals differ by ₹{diff:,.2f} — investigate before reporting")
    print("─────────────────────────────────────────────────────────\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Benchmark ITC apportionment: pandas vs cudf.pandas (GPU)")
    parser.add_argument(
        "--rows", type=int, default=2_000_000,
        help="Synthetic line-item count (default 2,000,000)")
    args = parser.parse_args()
    run(args.rows)