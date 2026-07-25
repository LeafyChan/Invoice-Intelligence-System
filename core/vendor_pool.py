"""
vendor_pool.py — Issue 13: Synthetic Data Vendor Repetition Fix
================================================================
Drop this file into your synthetic data generator folder and import
VENDOR_POOL + weighted_vendor_pick() wherever vendor names are assigned.

PROBLEM: The old generator created a unique vendor per transaction, so
the vendor scoring engine never accumulated enough history per vendor to
produce meaningful grades. Every vendor had 1 invoice = useless scores.

FIX: A pool of 15 vendors with weighted selection so the top 5 each get
8-10 transactions across a 50-doc dataset, giving the vendor intelligence
feature something real to display.

USAGE in your assembler/generator:
    from vendor_pool import weighted_vendor_pick, VENDOR_POOL

    # Replace:  vendor_name = fake.company()
    # With:     vendor = weighted_vendor_pick()
    #           vendor_name = vendor["name"]
    #           vendor_gstin = vendor["gstin"]
"""

import random

# ── 15 realistic Indian vendor names with GSTINs ─────────────────────────────
# GSTINs are synthetic (correct format: 2-digit state + 10-char PAN + Z + 1).
# State code 27 = Maharashtra (most common for B2B demos).

VENDOR_POOL = [
    # ── Top 5 — high-frequency, Grade A/B targets ──────────────────────────
    {
        "name": "Tata Steel Limited",
        "gstin": "27AAACT2727Q1ZV",
        "hsn_codes": ["7208", "7209", "7210"],
        "tier": "top",
    },
    {
        "name": "Mahindra Logistics Ltd",
        "gstin": "27AABCM1234R1ZP",
        "hsn_codes": ["9965", "9967"],
        "tier": "top",
    },
    {
        "name": "Reliance Industries Ltd",
        "gstin": "27AAACR5055K1ZZ",
        "hsn_codes": ["2710", "3901", "3902"],
        "tier": "top",
    },
    {
        "name": "Larsen & Toubro Infotech",
        "gstin": "27AABCL4769P1ZX",
        "hsn_codes": ["9983", "8471"],
        "tier": "top",
    },
    {
        "name": "Hindustan Unilever Ltd",
        "gstin": "27AAACH1439R1ZB",
        "hsn_codes": ["3401", "3402", "2101"],
        "tier": "top",
    },

    # ── Mid tier — occasional suppliers ──────────────────────────────────
    {
        "name": "Asian Paints Limited",
        "gstin": "27AAACA4803F1ZA",
        "hsn_codes": ["3208", "3209"],
        "tier": "mid",
    },
    {
        "name": "Bosch Limited",
        "gstin": "29AAACB3584N1ZA",
        "hsn_codes": ["8407", "8708"],
        "tier": "mid",
    },
    {
        "name": "Wipro Infrastructure Engineering",
        "gstin": "29AAACW0526G1ZA",
        "hsn_codes": ["8412", "8413"],
        "tier": "mid",
    },
    {
        "name": "Godrej & Boyce Mfg Co Ltd",
        "gstin": "27AAACG0816J1ZK",
        "hsn_codes": ["8418", "8422"],
        "tier": "mid",
    },
    {
        "name": "ITC Limited",
        "gstin": "19AAACI1685R1ZE",
        "hsn_codes": ["2402", "4802"],
        "tier": "mid",
    },

    # ── Tail vendors — rare, varied, some with quality issues ─────────────
    {
        "name": "Pune Precision Components",
        "gstin": "27AACPP1234K1ZQ",
        "hsn_codes": ["8484", "8466"],
        "tier": "tail",
    },
    {
        "name": "Bharat Packaging Works",
        "gstin": "27AABCB5678M1ZR",
        "hsn_codes": ["4819", "3923"],
        "tier": "tail",
    },
    {
        "name": "Nagpur Steel Traders",
        "gstin": "27AACCN9012L1ZS",
        "hsn_codes": ["7214", "7216"],
        "tier": "tail",
    },
    {
        "name": "Chennai Print House",
        "gstin": "33AACCC3456H1ZT",
        "hsn_codes": ["4901", "4911"],
        "tier": "tail",
    },
    {
        "name": "New Vendor (unregistered)",
        "gstin": None,
        "hsn_codes": ["9983"],
        "tier": "new",
    },
]

_TOP    = [v for v in VENDOR_POOL if v["tier"] == "top"]
_MID    = [v for v in VENDOR_POOL if v["tier"] == "mid"]
_TAIL   = [v for v in VENDOR_POOL if v["tier"] == "tail"]
_NEW    = [v for v in VENDOR_POOL if v["tier"] == "new"]


def weighted_vendor_pick() -> dict:
    """
    Returns one vendor dict from VENDOR_POOL with weighted probability:
      60% — top 5 vendors  (8-10 transactions in a 50-doc dataset)
      30% — mid 5 vendors  (2-4 transactions each)
      10% — tail + new     (0-2 transactions each)

    This ensures the vendor scorecard has at least 3 vendors with Grade A/B
    profiles and enough transaction history to show meaningful grading signals.
    """
    roll = random.random()
    if roll < 0.60:
        return random.choice(_TOP)
    elif roll < 0.90:
        return random.choice(_MID)
    elif roll < 0.97:
        return random.choice(_TAIL)
    else:
        return random.choice(_NEW)


# ── Integration example ───────────────────────────────────────────────────────
# In your transaction/document assembler, replace:
#
#   vendor_name  = fake.company()
#   vendor_gstin = fake_gstin()
#
# With:
#
#   from vendor_pool import weighted_vendor_pick
#   _v = weighted_vendor_pick()
#   vendor_name  = _v["name"]
#   vendor_gstin = _v["gstin"]          # may be None for unregistered
#   hsn_codes    = _v["hsn_codes"]      # use these for line item HSN fields
#
# For Issue 8 alignment: the simulated business should have outward supply
# HSN codes that are DIFFERENT from what vendors supply (e.g. if the simulated
# business is a furniture manufacturer, its outward HSNs are 9401/9403 while
# its inward purchase HSNs from vendors are 4403/7214/8466 etc).

if __name__ == "__main__":
    # Quick distribution test
    from collections import Counter
    results = Counter(weighted_vendor_pick()["name"] for _ in range(500))
    for name, count in results.most_common():
        bar = "█" * (count // 5)
        print(f"{name[:35]:<35} {count:>3}  {bar}")