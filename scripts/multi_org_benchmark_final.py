"""
multi_org_benchmark_final.py
=============================
Invoice Intelligence — definitive multi-org GPU benchmark.
Three strategies compared:

  A) pandas sequential     — one org at a time on CPU (production baseline)
  B) GPU streamed          — naive: small batches through GPU one-at-a-time.
                             LOSES to pandas at 100K rows/org.
                             PCIe transfer cost > compute saving. Documented
                             honestly — this is what you get if you naively
                             "add GPU" to a per-tenant loop.
  C) GPU cross-org batch   — THE CORRECT PRODUCTION ARCHITECTURE.
                             Concatenate N orgs into one large DataFrame,
                             single H->D transfer, one kernel over all rows,
                             groupby(org_id) to split results.
                             org_id is just a column. Recovers 5-8x speedup.

WHY THIS MATTERS (not "1s vs 0.5s"):
  Indian SME accumulates 5-20M line items over 3-5 years.
  At 20M rows, /itc-summary takes 2.35s on pandas vs 208ms on GPU --
  the difference between "waiting" and "instant". (cudf_benchmark.py)
  Nightly batch across all tenants:
    pandas sequential  : ~16s  (1,000 orgs, 100M rows)
    GPU cross-batch    :  ~2s  (same workload, Strategy C)
  At 10,000 orgs: ~2 min vs ~16 min. Operationally meaningful.

EXPECTED RESULTS (RTX 4050 6GB, WSL2, CUDA 12):
  Strategy A pandas     : ~11-16s
  Strategy B GPU stream : slower than A (PCIe dominates at 100K rows/org)
  Strategy C GPU cross  :  ~2-4s  (5-8x over pandas)

USAGE:
    python scripts/multi_org_benchmark_final.py
    python scripts/multi_org_benchmark_final.py --orgs 200
    python scripts/multi_org_benchmark_final.py --macro-batch 50
    python scripts/multi_org_benchmark_final.py --pandas-only
    python scripts/multi_org_benchmark_final.py --skip-streamed
"""

import argparse
import gc
import time
import concurrent.futures

import numpy as np
import pandas as pd_plain


# -- Domain data ---------------------------------------------------------------

INDUSTRIES = [
    "Manufacturing", "Retail", "IT Services", "Auto Parts",
    "Food Tech", "Pharma", "Logistics", "FMCG", "Textile", "Energy",
]

VENDOR_POOLS = {
    "Manufacturing": ["SAIL Distributors", "Tisco Metals", "JSW Steel Traders",
                      "Hindalco Alloys", "Vedanta Copper", "NALCO Dealers"],
    "Retail":        ["ITC Agro Pvt Ltd", "HUL Distributors", "Nestle India Agents",
                      "P&G Trade Partners", "Britannia Vendors", "Marico Traders"],
    "IT Services":   ["Dell Technologies IN", "HP Enterprise India", "Lenovo B2B",
                      "Cisco Systems India", "Wipro Infra", "Tata Elxsi Vendors"],
    "Auto Parts":    ["Bosch India Auto", "Minda Industries", "Motherson Sumi",
                      "Bharat Forge Tier2", "Sandvik Coromant", "SKF Bearings IN"],
    "Food Tech":     ["Sealed Air India", "Uflex Packaging", "TCPL Packaging",
                      "Huhtamaki PPL", "Essel Propack", "Manjushree Technopack"],
    "Pharma":        ["Sun Pharma Suppliers", "Cipla Vendors", "Dr Reddy Chemicals",
                      "Aurobindo API", "Divi Labs Traders", "Lupin Distributors"],
    "Logistics":     ["Blue Dart Partners", "DTDC Vendors", "Gati Express",
                      "Mahindra Logistics", "TCI Supply Chain", "Rivigo Traders"],
    "FMCG":          ["Dabur Suppliers", "Godrej Vendors", "Emami Distributors",
                      "Himalaya Traders", "Patanjali Vendors", "CavinKare Partners"],
    "Textile":       ["Vardhman Fabrics", "Welspun India", "Raymond Textiles",
                      "Arvind Mills", "RSWM Limited", "Grasim Industries"],
    "Energy":        ["NTPC Vendors", "Adani Power Traders", "Tata Power Suppliers",
                      "BHEL Distributors", "Siemens India", "ABB India"],
}

HSN_CODES  = np.array(["7308","8481","3926","4820","8471","9403",
                        "2710","5407","7318","8536","3923","6802"], dtype=object)
HSN_STATUS = np.array(["expected","expected","expected","expected","ambiguous","expected",
                        "ambiguous","expected","expected","unknown","expected","ambiguous"],
                       dtype=object)
GST_RATES  = np.array([0.05, 0.12, 0.18, 0.28])
GST_RATE_W = np.array([0.10, 0.20, 0.55, 0.15])
LTR_VALUES = np.array([np.nan, np.nan, 5.0, 12.0, 18.0, 28.0, np.nan])
BUP_VALUES = np.array([100., 100., 100., 100., 75., 50., 90.])


# -- Data generation -----------------------------------------------------------

def generate_org(org_id: int, n: int, industry: str, seed: int = 42) -> pd_plain.DataFrame:
    """Generate n synthetic line items for one org. ~14 MB at 100K rows."""
    rng     = np.random.default_rng(seed + org_id * 1337)
    vendors = np.array(VENDOR_POOLS[industry], dtype=object)

    n_inv_est     = n // 2 + 100
    lines_per_inv = rng.integers(1, 6, size=n_inv_est)
    cumsum        = np.cumsum(lines_per_inv)
    n_inv_needed  = int(np.searchsorted(cumsum, n, side="left")) + 1
    inv_ids       = np.repeat(np.arange(n_inv_needed, dtype=np.int32),
                              lines_per_inv[:n_inv_needed])[:n]
    taxable_inv = np.round(rng.uniform(500, 200_000, size=n_inv_needed), 2)
    rate_idx    = rng.choice(len(GST_RATES), size=n_inv_needed, p=GST_RATE_W)
    gst_inv     = np.round(taxable_inv * GST_RATES[rate_idx], 2)

    return pd_plain.DataFrame({
        "org_id":                np.full(n, org_id, dtype=np.int32),
        "invoice_id":            inv_ids,
        "vendor_name":           vendors[rng.integers(0, len(vendors), size=n)],
        "hsn_status":            HSN_STATUS[rng.integers(0, len(HSN_CODES), size=n)],
        "amount":                np.round(taxable_inv[inv_ids] * rng.uniform(0.7, 1.3, size=n), 2),
        "taxable_amount":        taxable_inv[inv_ids],
        "total_gst_amount":      gst_inv[inv_ids],
        "business_use_percent":  BUP_VALUES[rng.integers(0, len(BUP_VALUES), size=n)],
        "line_tax_rate_percent": LTR_VALUES[rng.integers(0, len(LTR_VALUES), size=n)],
    })


# -- ITC computation -----------------------------------------------------------

def compute_itc(df) -> float:
    """ITC apportionment -- same math as production /itc-summary route."""
    biz_pct            = df["business_use_percent"].fillna(100) / 100.0
    has_line_rate      = df["line_tax_rate_percent"].notna()
    line_tax_rate      = df["amount"] * df["line_tax_rate_percent"].fillna(0) / 100.0
    line_tax_apportion = df["total_gst_amount"] * (
        df["amount"] / df["taxable_amount"].replace(0, float("nan"))
    )
    line_tax  = line_tax_rate.where(has_line_rate, line_tax_apportion.fillna(0))
    claimable = line_tax * biz_pct
    return float(claimable.sum())


def compute_itc_by_org(df) -> dict:
    """
    Cross-org batch compute. org_id is just a column.
    One vectorized pass + groupby(org_id) -- single GPU kernel.
    Tenant isolation is a groupby, not a loop.
    """
    biz_pct            = df["business_use_percent"].fillna(100) / 100.0
    has_line_rate      = df["line_tax_rate_percent"].notna()
    line_tax_rate      = df["amount"] * df["line_tax_rate_percent"].fillna(0) / 100.0
    line_tax_apportion = df["total_gst_amount"] * (
        df["amount"] / df["taxable_amount"].replace(0, float("nan"))
    )
    line_tax  = line_tax_rate.where(has_line_rate, line_tax_apportion.fillna(0))
    claimable = line_tax * biz_pct
    by_org    = claimable.groupby(df["org_id"]).sum()
    return {int(k): float(v) for k, v in by_org.items()}


# -- Strategy A: pandas sequential ---------------------------------------------

def run_pandas(n_orgs: int, rows_per_org: int, industries: list) -> tuple:
    """One org at a time on CPU. Peak RAM ~14 MB. Production baseline."""
    results = {}
    t_start = time.perf_counter()
    for org_id in range(n_orgs):
        df = generate_org(org_id, rows_per_org, industries[org_id])
        results[org_id] = compute_itc(df)
        del df
        if (org_id + 1) % 100 == 0:
            elapsed = time.perf_counter() - t_start
            eta = elapsed / (org_id + 1) * (n_orgs - org_id - 1)
            print(f"    pandas [{org_id+1:>4}/{n_orgs}]  "
                  f"{elapsed:6.2f}s  ETA {eta:5.1f}s  "
                  f"{(org_id+1)*rows_per_org:,} rows done")
    return time.perf_counter() - t_start, results


# -- Strategy B: GPU streamed (naive -- documented to show why it loses) -------

def run_gpu_streamed(n_orgs, rows_per_org, industries, batch_size, pd_gpu) -> tuple:
    """
    Naive GPU: transfer one small batch at a time.
    Loses to pandas because each org (~14 MB) is too small to amortize PCIe.
    Kept for honest documentation -- this is what you get with a per-tenant loop.
    """
    results = {}
    t_start = time.perf_counter()
    org_id  = 0

    def _one(cpu_df):
        gpu_df = pd_gpu.DataFrame(cpu_df)
        total  = compute_itc(gpu_df)
        del gpu_df
        return total

    while org_id < n_orgs:
        batch_end = min(org_id + batch_size, n_orgs)
        cpu_dfs = [generate_org(oid, rows_per_org, industries[oid])
                   for oid in range(org_id, batch_end)]
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(cpu_dfs)) as pool:
            totals = list(pool.map(_one, cpu_dfs))
        for oid, total in zip(range(org_id, batch_end), totals):
            results[oid] = total
        del cpu_dfs; gc.collect()
        org_id = batch_end
        if org_id % 100 == 0 or org_id == n_orgs:
            elapsed = time.perf_counter() - t_start
            eta = elapsed / org_id * (n_orgs - org_id) if org_id < n_orgs else 0
            print(f"    GPU-stream [{org_id:>4}/{n_orgs}]  "
                  f"{elapsed:6.2f}s  ETA {eta:5.1f}s")
    return time.perf_counter() - t_start, results


# -- Strategy C: GPU cross-org batch (correct production pattern) --------------

def run_gpu_cross_batch(n_orgs, rows_per_org, industries, macro_batch, pd_gpu) -> tuple:
    """
    THE CORRECT MULTI-TENANT GPU ARCHITECTURE.

    Key insight: org_id is just a column. Instead of looping per-org,
    concatenate macro_batch orgs before the GPU transfer:

      1. Generate macro_batch orgs on CPU       (macro_batch x 14 MB)
      2. pd.concat -> one large DataFrame        (org_id column preserved)
      3. Single H->D transfer                    (now compute-bound)
      4. One vectorized pass + groupby(org_id)   (one GPU kernel)
      5. Split results by org_id                 (tenant isolation here)
      6. Discard, GC, next macro-batch

    At macro_batch=100: 10M rows per transfer -> GPU wins decisively.
    At macro_batch=50 : 5M rows              -> still wins.
    Below ~20 orgs (2M rows): advantage narrows toward break-even.
    """
    results = {}
    t_start = time.perf_counter()
    org_id  = 0
    xfer_mb_total = 0.0

    while org_id < n_orgs:
        batch_end = min(org_id + macro_batch, n_orgs)
        batch_ids = list(range(org_id, batch_end))

        cpu_dfs = [generate_org(oid, rows_per_org, industries[oid]) for oid in batch_ids]
        combined_cpu = pd_plain.concat(cpu_dfs, ignore_index=True)
        xfer_mb = combined_cpu.memory_usage(deep=False).sum() / 1024**2
        xfer_mb_total += xfer_mb
        del cpu_dfs

        combined_gpu  = pd_gpu.DataFrame(combined_cpu)
        del combined_cpu
        results.update(compute_itc_by_org(combined_gpu))
        del combined_gpu; gc.collect()

        org_id = batch_end
        if org_id % 100 == 0 or org_id == n_orgs:
            elapsed = time.perf_counter() - t_start
            eta = elapsed / org_id * (n_orgs - org_id) if org_id < n_orgs else 0
            print(f"    GPU-cross [{org_id:>4}/{n_orgs}]  "
                  f"{elapsed:6.2f}s  ETA {eta:5.1f}s  "
                  f"total xfer {xfer_mb_total:.0f} MB")
    return time.perf_counter() - t_start, results


# -- Output helpers ------------------------------------------------------------

def print_sample(label, wall, results, industries, rows_per_org, n=5):
    ids  = sorted(results.keys())
    show = ids[:n] + (ids[-n:] if len(ids) > n * 2 else [])
    print(f"\n{chr(8212)*80}")
    print(f"  {label}   |   wall-clock: {wall:.3f}s")
    print(f"{chr(8212)*80}")
    print(f"  {'OrgID':>6}  {'Industry':<16} {'Rows':>8}  {'ITC Total':>20}")
    for i, oid in enumerate(show):
        if i == n and len(ids) > n * 2:
            print(f"        ... {len(results) - n*2} orgs not shown ...")
        print(f"  {oid:>6}  {industries[oid]:<16} {rows_per_org:>8,}  "
              f"Rs{results[oid]:>19,.0f}")
    print(f"{chr(8212)*80}")


def verify(pr, gr):
    mm = [o for o in pr if abs(pr[o] - gr.get(o, 0)) >= 1.0]
    return ("Yes" if not mm else f"NO - {len(mm)} mismatches"), len(mm)


def print_summary(n_orgs, rows_per_org, pt, st=None, ct=None, sm=None, cm=None):
    total = n_orgs * rows_per_org
    print(f"\n{chr(9552)*80}")
    print(f"  RESULTS SUMMARY -- Invoice Intelligence Multi-Org GPU Benchmark")
    print(f"{chr(9552)*80}")
    print(f"  Total rows      : {total:,}")
    print(f"  Organisations   : {n_orgs:,}   |   Rows per org: {rows_per_org:,} (~14 MB each)")
    print()
    print(f"  A) pandas sequential   : {pt:.3f}s  ({pt/n_orgs*1000:.1f} ms/org)")
    if st is not None:
        s = pt / st
        v = "WINS" if s > 1.05 else "LOSES to pandas -- PCIe overhead > compute gain"
        print(f"  B) GPU streamed        : {st:.3f}s  ({s:.1f}x)  {v}")
        print(f"     results match       : {sm}")
    if ct is not None:
        s = pt / ct
        v = "WINS -- compute-bound, not transfer-bound" if s > 1.05 else "marginal"
        print(f"  C) GPU cross-org batch : {ct:.3f}s  ({s:.1f}x)  {v}")
        print(f"     results match       : {cm}")
    print()
    print(f"  KEY INSIGHT:")
    print(f"  B loses because each org (~14 MB) is too small to amortize PCIe cost.")
    print(f"  C concatenates orgs BEFORE transfer -- large compute-bound kernel.")
    print(f"  org_id is just a groupby column. Tenant isolation is not a GPU concern.")
    print()
    print(f"  BUSINESS CASE:")
    print(f"  /itc-summary at 20M rows: 208ms (GPU) vs 2.35s (pandas) = 11.3x")
    print(f"  Nightly batch 1,000 orgs: {ct:.1f}s vs {pt:.1f}s" if ct else "")
    if ct:
        print(f"  At 10,000 orgs: ~{ct/n_orgs*10000/60:.0f} min vs ~{pt/n_orgs*10000/60:.0f} min")
    print(f"  (See cudf_benchmark.py --rows 20000000 for single-org peak)")
    print(f"{chr(9552)*80}\n")


# -- Main ----------------------------------------------------------------------

def run(n_orgs, rows_per_org, batch_size, macro_batch, pandas_only, skip_streamed):
    industries = [INDUSTRIES[i % len(INDUSTRIES)] for i in range(n_orgs)]

    print(f"\n{chr(9552)*80}")
    print(f"  Invoice Intelligence -- Multi-Org GPU Benchmark (3 strategies)")
    print(f"  {n_orgs:,} orgs  x  {rows_per_org:,} rows  =  {n_orgs*rows_per_org:,} total  |  RTX 4050")
    print(f"{chr(9552)*80}")

    print(f"\n  [A] pandas sequential...")
    pt, pr = run_pandas(n_orgs, rows_per_org, industries)
    print_sample("A) pandas sequential", pt, pr, industries, rows_per_org)

    if pandas_only:
        print_summary(n_orgs, rows_per_org, pt)
        return

    try:
        import rmm
        rmm.reinitialize(pool_allocator=True,
                         initial_pool_size=256*1024*1024,
                         maximum_pool_size=5*1024*1024*1024)
        import cudf.pandas; cudf.pandas.install()
        import pandas as pd_gpu
        print("\n  GPU warm-up (CUDA JIT, not timed)...")
        _w = pd_gpu.DataFrame(generate_org(0, 1000, INDUSTRIES[0]))
        compute_itc(_w); del _w; gc.collect()
        print("  GPU ready.\n")
    except ImportError:
        print("  cuDF not installed: pip install cudf-cu12 --extra-index-url=https://pypi.nvidia.com")
        print_summary(n_orgs, rows_per_org, pt); return
    except Exception as e:
        print(f"  GPU init failed: {e}")
        import traceback; traceback.print_exc()
        print_summary(n_orgs, rows_per_org, pt); return

    st = sm = None
    if not skip_streamed:
        print(f"  [B] GPU streamed (naive, batch={batch_size}) -- expect LOSS at {rows_per_org:,} rows/org...")
        st, sr = run_gpu_streamed(n_orgs, rows_per_org, industries, batch_size, pd_gpu)
        print_sample(f"B) GPU streamed (batch={batch_size})", st, sr, industries, rows_per_org)
        sm, _ = verify(pr, sr)
        gc.collect()

    print(f"\n  [C] GPU cross-org batch (macro={macro_batch}) -- {macro_batch*rows_per_org:,} rows per transfer...")
    ct, cr = run_gpu_cross_batch(n_orgs, rows_per_org, industries, macro_batch, pd_gpu)
    print_sample(f"C) GPU cross-org batch (macro={macro_batch})", ct, cr, industries, rows_per_org)
    cm, _ = verify(pr, cr)

    print_summary(n_orgs, rows_per_org, pt, st, ct, sm, cm)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--orgs",          type=int, default=1000)
    p.add_argument("--rows-per-org",  type=int, default=100_000)
    p.add_argument("--batch",         type=int, default=8)
    p.add_argument("--macro-batch",   type=int, default=100,
                   help="Orgs concatenated before GPU transfer (default 100 = 10M rows/xfer)")
    p.add_argument("--pandas-only",   action="store_true")
    p.add_argument("--skip-streamed", action="store_true")
    a = p.parse_args()
    run(a.orgs, a.rows_per_org, a.batch, a.macro_batch, a.pandas_only, a.skip_streamed)