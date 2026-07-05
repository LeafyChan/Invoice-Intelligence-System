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
    python scripts/cudf_benchmark.py            # default 100k rows
    python scripts/cudf_benchmark.py --rows 500000

OUTPUT:
    pandas:       X.XXXs
    cudf.pandas:  X.XXXs
    speedup:      Nx
    results match: True

The speedup number + this script output is the NVIDIA acceleration
evidence for the hackathon submission.
"""

import argparse
import random
import time
import uuid
from datetime import date, timedelta

# ── Synthetic data generator ───────────────────────────────────────────────────
# Shaped like bigquery_sync.py's LINE_ITEMS_QUERY output — same columns
# main.py's itc_summary route aggregates. Messy vendor name variants on
# purpose (same GSTIN, 2-4 spellings) to mirror the real-world problem.

random.seed(42)

VENDOR_BASES = [
    "Metro Cash Carry", "Shree Traders", "ABC Metals", "XYZ Hardware",
    "Global Enterprises", "National Suppliers", "Prime Industrial",
    "Sunrise Textiles", "Om Sai Traders", "Deccan Steel Corp",
    "Krishna Electricals", "Bharat Packaging", "Vishal Chemicals",
    "Lakshmi Timber Mart", "Ganesh Auto Parts", "Star Logistics",
    "Modern Furnishings", "United Plastics", "Kumar Distributors",
    "Reliable Fasteners",
]
HSN_POOL = [
    ("7308", "expected"), ("8481", "expected"), ("3926", "expected"),
    ("4820", "expected"), ("8471", "ambiguous"), ("9403", "expected"),
    ("2710", "ambiguous"), ("5407", "expected"), ("7318", "expected"),
    ("8536", "unknown"),  ("3923", "expected"), ("6802", "ambiguous"),
]
STATES = ["27", "29", "33", "36", "07", "19", "24"]


def _make_vendors():
    vendors = []
    for base in VENDOR_BASES:
        state = random.choice(STATES)
        pan = "".join(random.choices("ABCDEFGHIJKLMNOPQRSTUVWXYZ", k=5)) + \
              "".join(random.choices("0123456789", k=4)) + \
              random.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
        gstin = f"{state}{pan}1Z{random.choice('0123456789')}"
        variants = [
            f"{base} Pvt Ltd", f"{base} Traders",
            "".join(w[0] for w in base.split()).upper() + " C&C",
            f"{base} & Co",
        ]
        vendors.append({"gstin": gstin, "names": variants})
    return vendors


def generate_rows(n: int) -> list[dict]:
    vendors = _make_vendors()
    start = date(2025, 4, 1)
    rows = []
    inv_id = vendor = vendor_name = vendor_gstin = None
    inv_date = taxable = gst = None
    per_inv = 0
    count = 0

    for _ in range(n):
        if count == 0:
            inv_id = str(uuid.uuid4())
            vendor = random.choice(vendors)
            vendor_name = random.choice(vendor["names"])
            vendor_gstin = vendor["gstin"]
            inv_date = (start + timedelta(days=random.randint(0, 420))).isoformat()
            taxable = round(random.uniform(500, 200_000), 2)
            gst = round(taxable * random.choice([0.05, 0.12, 0.18, 0.28]), 2)
            per_inv = random.randint(1, 5)
            count = per_inv

        hsn_code, hsn_status = random.choice(HSN_POOL)
        amount = round(taxable / per_inv * random.uniform(0.7, 1.3), 2)
        bup = random.choice([100, 100, 100, 100, 75, 50, 90])
        ltr = random.choice([None, None, 5, 12, 18, 28])

        rows.append({
            "line_item_id":          str(uuid.uuid4()),
            "invoice_id":            inv_id,
            "vendor_name":           vendor_name,
            "vendor_gstin":          vendor_gstin,
            "hsn_code":              hsn_code,
            "hsn_status":            hsn_status,
            "amount":                amount,
            "taxable_amount":        taxable,
            "total_gst_amount":      gst,
            "business_use_percent":  float(bup),
            "line_tax_rate_percent": float(ltr) if ltr else None,
            "invoice_date":          inv_date,
            "status":                "PASSED",
        })
        count -= 1

    return rows


# ── ITC apportionment — identical to main.py's /itc-summary logic ─────────────

def compute_itc_summary(df, pd_module):
    """Same math as main.py's itc_summary route, vectorized.
    pd_module is either `pandas` or `cudf` (via cudf.pandas import)."""
    pd = pd_module
    d = df.copy()
    d["biz_pct"] = d["business_use_percent"].fillna(100) / 100.0

    has_line_rate = d["line_tax_rate_percent"].notna()
    line_tax_rate = d["amount"] * d["line_tax_rate_percent"].fillna(0) / 100.0
    line_tax_apportion = d["total_gst_amount"] * (
        d["amount"] / d["taxable_amount"].replace(0, float("nan"))
    )
    d["line_tax"] = line_tax_rate.where(has_line_rate, line_tax_apportion.fillna(0))
    d["claimable"] = d["line_tax"] * d["biz_pct"]

    total = float(d["claimable"].sum())
    by_vendor = d.groupby("vendor_name")["claimable"].sum().sort_values(ascending=False)
    by_hsn = d.groupby("hsn_status")["claimable"].sum()
    return total, by_vendor, by_hsn


# ── Benchmark runner ──────────────────────────────────────────────────────────

def run(n_rows: int):
    print(f"\nGenerating {n_rows:,} synthetic line items…")
    rows = generate_rows(n_rows)
    print(f"Done — {len(rows):,} rows, {len({r['vendor_name'] for r in rows})} vendor name variants")

    # ── pandas baseline ──
    print("\n[1/2] pandas baseline…")
    import pandas as pd_plain
    df_cpu = pd_plain.DataFrame(rows)
    t0 = time.perf_counter()
    total_cpu, by_vendor_cpu, _ = compute_itc_summary(df_cpu, pd_plain)
    pandas_time = time.perf_counter() - t0
    print(f"  total claimable ITC : ₹{total_cpu:,.2f}")
    print(f"  wall-clock          : {pandas_time:.3f}s")

    # ── cudf.pandas ──
    print("\n[2/2] cudf.pandas (GPU)…")
    try:
        # Cap RMM pool to 2GB before cudf.pandas.install() — RTX 4050 has
        # 6GB VRAM but ~300MB is reserved by the display driver under
        # WSL2+Windows, so the default "allocate everything" pool fails at
        # ~4GB. 2GB is safe and enough for 100k-500k rows.
        import rmm
        rmm.reinitialize(
            pool_allocator=True,
            initial_pool_size=512 * 1024 * 1024,      # 512 MB initial
            maximum_pool_size=2 * 1024 * 1024 * 1024, # 2 GB max
        )
        import cudf.pandas
        cudf.pandas.install()
        import pandas as pd_gpu  # now GPU-backed
        df_gpu = pd_gpu.DataFrame(rows)
        # warm-up (first GPU call includes JIT overhead — not representative)
        _ = compute_itc_summary(df_gpu, pd_gpu)
        t0 = time.perf_counter()
        total_gpu, by_vendor_gpu, _ = compute_itc_summary(df_gpu, pd_gpu)
        gpu_time = time.perf_counter() - t0
        print(f"  total claimable ITC : ₹{float(total_gpu):,.2f}")
        print(f"  wall-clock          : {gpu_time:.3f}s")
    except ImportError:
        print("  cudf not installed. Run:")
        print("  pip install cudf-cu12 --extra-index-url=https://pypi.nvidia.com")
        return

    # ── comparison ──
    speedup = pandas_time / gpu_time if gpu_time > 0 else float("inf")
    match = abs(total_cpu - float(total_gpu)) < 1.0

    print("\n── Results ──────────────────────────────────────")
    print(f"  pandas:       {pandas_time:.3f}s")
    print(f"  cudf.pandas:  {gpu_time:.3f}s")
    print(f"  speedup:      {speedup:.1f}x")
    print(f"  results match: {match}")
    if not match:
        print(f"  WARNING: totals differ by ₹{abs(total_cpu - float(total_gpu)):,.2f} — investigate before reporting")
    print("─────────────────────────────────────────────────\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows", type=int, default=100_000,
                        help="Number of synthetic line items (default 100000)")
    args = parser.parse_args()
    run(args.rows)