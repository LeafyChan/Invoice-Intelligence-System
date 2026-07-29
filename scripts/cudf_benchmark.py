import argparse
import time
import numpy as np
import pandas as pd_plain
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
GST_RATES = np.array([0.05, 0.12, 0.18, 0.28])
GST_RATE_W = np.array([0.10, 0.20, 0.55, 0.15])
LTR_VALUES = np.array([np.nan, np.nan, 5.0, 12.0, 18.0, 28.0, np.nan])
BUP_VALUES  = np.array([100., 100., 100., 100., 75., 50., 90.])

def generate_dataframe(n: int, pd_mod=pd_plain) -> "pd_mod.DataFrame":
    rng = np.random.default_rng(42)
    n_inv_est = n // 2 + 1000          
    lines_per_inv = rng.integers(1, 6, size=n_inv_est)
    cumsum        = np.cumsum(lines_per_inv)
    n_inv_needed  = int(np.searchsorted(cumsum, n, side="left")) + 1
    lines_per_inv = lines_per_inv[:n_inv_needed]
    inv_ids_per_line_full = np.repeat(np.arange(n_inv_needed, dtype=np.int32),
                                      lines_per_inv)[:n]
    taxable_inv = np.round(rng.uniform(500, 200_000, size=n_inv_needed), 2)
    rate_idx    = rng.choice(len(GST_RATES), size=n_inv_needed, p=GST_RATE_W)
    gst_inv     = np.round(taxable_inv * GST_RATES[rate_idx], 2)
    inv_ids_per_line = inv_ids_per_line_full
    taxable_per_line = taxable_inv[inv_ids_per_line]
    gst_per_line     = gst_inv[inv_ids_per_line]
    vendor_idx  = rng.integers(0, len(VENDOR_NAMES), size=n)
    vendor_name = VENDOR_NAMES[vendor_idx]
    hsn_idx  = rng.integers(0, len(HSN_CODES), size=n)
    hsn_code = HSN_CODES[hsn_idx]
    hsn_stat = HSN_STATUS[hsn_idx]
    jitter = rng.uniform(0.7, 1.3, size=n)
    amount = np.round(taxable_per_line * jitter, 2)
    bup_idx = rng.integers(0, len(BUP_VALUES), size=n)
    bup     = BUP_VALUES[bup_idx]

    ltr_idx = rng.integers(0, len(LTR_VALUES), size=n)
    ltr     = LTR_VALUES[ltr_idx]
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

def run(n_rows: int):
    print(f"\nGenerating {n_rows:,} synthetic line items (numpy path)…")
    t_gen = time.perf_counter()
    df_cpu = generate_dataframe(n_rows, pd_mod=pd_plain)
    gen_time = time.perf_counter() - t_gen
    n_vendors = df_cpu["vendor_name"].nunique()
    mem_mb    = df_cpu.memory_usage(deep=True).sum() / 1024**2
    print(f"  done in {gen_time:.2f}s — {n_vendors} vendor variants, "
          f"DataFrame RAM ≈ {mem_mb:.0f} MB")
    print("\n[1/2] pandas baseline…")
    _ = compute_itc_summary(df_cpu.head(1000))
    t0 = time.perf_counter()
    total_cpu, by_vendor_cpu, _ = compute_itc_summary(df_cpu)
    pandas_time = time.perf_counter() - t0
    print(f"  total claimable ITC : ₹{total_cpu:,.2f}")
    print(f"  top vendor          : {by_vendor_cpu.index[0]}")
    print(f"  wall-clock          : {pandas_time:.3f}s")
    print("\n[2/2] cudf.pandas (GPU)…")
    try:
        import rmm
        rmm.reinitialize(
            pool_allocator=True,
            initial_pool_size=512  * 1024 * 1024,      
            maximum_pool_size=5    * 1024 * 1024 * 1024, 
        )
        import cudf.pandas
        cudf.pandas.install()
        import pandas as pd_gpu   
        print("  transferring DataFrame to GPU…")
        t_xfer = time.perf_counter()
        df_gpu = pd_gpu.DataFrame(df_cpu)             
        xfer_time = time.perf_counter() - t_xfer
        print(f"  H→D transfer        : {xfer_time:.3f}s")

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