import random
VENDOR_POOL = [
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
    roll = random.random()
    if roll < 0.60:
        return random.choice(_TOP)
    elif roll < 0.90:
        return random.choice(_MID)
    elif roll < 0.97:
        return random.choice(_TAIL)
    else:
        return random.choice(_NEW)
if __name__ == "__main__":
    # Quick distribution test
    from collections import Counter
    results = Counter(weighted_vendor_pick()["name"] for _ in range(500))
    for name, count in results.most_common():
        bar = "█" * (count // 5)
        print(f"{name[:35]:<35} {count:>3}  {bar}")