import { useState, useRef, useEffect } from "react";

const PRESETS = [
  { label: "Today",     value: "today" },
  { label: "This week", value: "week"  },
  { label: "This month",value: "month" },
  { label: "Quarter",   value: "quarter"},
  { label: "This year", value: "year"  },
];

function getPresetDates(preset) {
  const now = new Date();
  const pad = n => String(n).padStart(2, "0");
  const iso = d => `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}`;
  const today = iso(now);
  if (preset === "today") return { from: today, to: today };
  if (preset === "week") {
    const d = new Date(now); d.setDate(d.getDate() - d.getDay());
    return { from: iso(d), to: today };
  }
  if (preset === "month") {
    return { from: `${now.getFullYear()}-${pad(now.getMonth()+1)}-01`, to: today };
  }
  if (preset === "quarter") {
    const q = Math.floor(now.getMonth() / 3);
    const start = new Date(now.getFullYear(), q * 3, 1);
    return { from: iso(start), to: today };
  }
  if (preset === "year") {
    return { from: `${now.getFullYear()}-01-01`, to: today };
  }
  return { from: "", to: "" };
}

const EMPTY = {
  search: "", vendor_gstin: "", invoice_number: "", po_number: "",
  mrn_number: "", grn_number: "", waybill_number: "",
  status: "", amount_min: "", amount_max: "",
  date_from: "", date_to: "", date_preset: "",
  paid: "", overdue_only: false,
};

function activeCount(f) {
  let n = 0;
  if (f.search)          n++;
  if (f.vendor_gstin)    n++;
  if (f.invoice_number)  n++;
  if (f.po_number)       n++;
  if (f.mrn_number)      n++;
  if (f.grn_number)      n++;
  if (f.waybill_number)  n++;
  if (f.status)          n++;
  if (f.amount_min)      n++;
  if (f.amount_max)      n++;
  if (f.date_from || f.date_to || f.date_preset) n++;
  if (f.paid !== "")     n++;
  if (f.overdue_only)    n++;
  return n;
}

const S = {
  wrap:    { fontFamily: "'Inter',system-ui,sans-serif", background: "#fff", borderBottom: "1px solid #E5E7EB" },
  bar:     { display: "flex", alignItems: "center", gap: 8, padding: "8px 16px", flexWrap: "wrap" },
  input:   { border: "1px solid #D1D5DB", borderRadius: 6, padding: "5px 10px", fontSize: 13, fontFamily: "inherit", outline: "none", background: "#FAFAFA" },
  btn:     { border: "none", borderRadius: 6, padding: "6px 14px", fontSize: 13, fontWeight: 600, cursor: "pointer", fontFamily: "inherit" },
  label:   { fontSize: 11, fontWeight: 600, color: "#6B7280", display: "block", marginBottom: 3 },
  panel:   { padding: "12px 16px 16px", borderTop: "1px solid #F1F5F9", display: "grid", gap: "10px 16px",
             gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))" },
  group:   { display: "flex", flexDirection: "column" },
  range:   { display: "flex", gap: 6, alignItems: "center" },
  badge:   { background: "#1E3A5F", color: "#fff", borderRadius: 10, fontSize: 10, fontWeight: 700,
             padding: "1px 6px", marginLeft: 2 },
  pill:    { border: "1px solid #D1D5DB", borderRadius: 6, padding: "3px 10px", fontSize: 12,
             cursor: "pointer", fontFamily: "inherit", background: "#fff", color: "#374151" },
  pillOn:  { background: "#1E3A5F", color: "#fff", border: "1px solid #1E3A5F" },
};

export default function AdvancedSearch({ onSearch, onClear }) {
  const [open, setOpen]     = useState(false);
  const [f, setF]           = useState({ ...EMPTY });
  const searchRef           = useRef(null);

  function set(key, val) { setF(p => ({ ...p, [key]: val })); }

  function applyPreset(preset) {
    const { from, to } = getPresetDates(preset);
    setF(p => ({ ...p, date_preset: preset, date_from: from, date_to: to }));
  }

  function handleSearch(e) {
    e?.preventDefault();
    const out = { ...f };
    if (out.amount_min) out.amount_min = parseFloat(out.amount_min) || null;
    else out.amount_min = null;
    if (out.amount_max) out.amount_max = parseFloat(out.amount_max) || null;
    else out.amount_max = null;
    if (out.paid === "true")  out.paid = true;
    else if (out.paid === "false") out.paid = false;
    else out.paid = null;
    onSearch(out);
  }

  function handleClear() {
    setF({ ...EMPTY });
    onClear?.();
  }

  const count = activeCount(f);
  useEffect(() => {
    function onKey(e) { if (e.key === "Escape" && open) setOpen(false); }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open]);

  return (
    <div style={S.wrap}>
      {/* ── Top bar ── */}
      <div style={S.bar}>
        {/* Main search input */}
        <input
          ref={searchRef}
          style={{ ...S.input, width: 240 }}
          placeholder="Search vendor / invoice / PO…"
          value={f.search}
          onChange={e => set("search", e.target.value)}
          onKeyDown={e => { if (e.key === "Enter") handleSearch(); }}
        />

        {/* Toggle advanced */}
        <button
          onClick={() => setOpen(o => !o)}
          style={{
            ...S.btn,
            background: open ? "#1E3A5F" : "#F1F5F9",
            color: open ? "#fff" : "#374151",
            display: "flex", alignItems: "center", gap: 4,
          }}
        >
          {open ? "▲" : "▼"} Filters
          {count > 0 && <span style={S.badge}>{count}</span>}
        </button>

        <button onClick={handleSearch} style={{ ...S.btn, background: "#1E3A5F", color: "#fff" }}>
          Search
        </button>

        {count > 0 && (
          <button onClick={handleClear} style={{ ...S.btn, background: "#FEE2E2", color: "#DC2626" }}>
            ✕ Clear
          </button>
        )}

        {/* Active filter pills (quick summary) */}
        {count > 0 && !open && (
          <div style={{ display: "flex", gap: 4, flexWrap: "wrap", fontSize: 11 }}>
            {f.status       && <span style={{ ...S.pill, background:"#EFF6FF", color:"#1D4ED8", border:"1px solid #BFDBFE" }}>{f.status}</span>}
            {f.date_preset  && <span style={{ ...S.pill, background:"#EFF6FF", color:"#1D4ED8", border:"1px solid #BFDBFE" }}>{PRESETS.find(p=>p.value===f.date_preset)?.label}</span>}
            {(f.amount_min||f.amount_max) && <span style={{ ...S.pill, background:"#EFF6FF", color:"#1D4ED8", border:"1px solid #BFDBFE" }}>₹{f.amount_min||"0"}–{f.amount_max||"∞"}</span>}
            {f.overdue_only && <span style={{ ...S.pill, background:"#FEE2E2", color:"#DC2626", border:"1px solid #FECACA" }}>Overdue</span>}
            {f.vendor_gstin && <span style={{ ...S.pill }}>{f.vendor_gstin}</span>}
          </div>
        )}
      </div>

      {/* ── Expanded panel ── */}
      {open && (
        <div style={S.panel}>

          {/* Vendor GSTIN */}
          <div style={S.group}>
            <label style={S.label}>Vendor GSTIN</label>
            <input style={S.input} placeholder="e.g. 29ABCDE1234F1Z5"
              value={f.vendor_gstin} onChange={e => set("vendor_gstin", e.target.value)} />
          </div>

          {/* Invoice number */}
          <div style={S.group}>
            <label style={S.label}>Invoice Number</label>
            <input style={S.input} placeholder="e.g. INV/2526/001"
              value={f.invoice_number} onChange={e => set("invoice_number", e.target.value)} />
          </div>

          {/* PO number */}
          <div style={S.group}>
            <label style={S.label}>PO Number</label>
            <input style={S.input} placeholder="e.g. PO-2024-001"
              value={f.po_number} onChange={e => set("po_number", e.target.value)} />
          </div>

          {/* Waybill number */}
          <div style={S.group}>
            <label style={S.label}>E-Waybill Number</label>
            <input style={S.input} placeholder="EWB number"
              value={f.waybill_number} onChange={e => set("waybill_number", e.target.value)} />
          </div>

          {/* GRN number */}
          <div style={S.group}>
            <label style={S.label}>GRN Number</label>
            <input style={S.input} placeholder="GRN number"
              value={f.grn_number} onChange={e => set("grn_number", e.target.value)} />
          </div>

          {/* MRN number */}
          <div style={S.group}>
            <label style={S.label}>MRN Number</label>
            <input style={S.input} placeholder="MRN number"
              value={f.mrn_number} onChange={e => set("mrn_number", e.target.value)} />
          </div>

          {/* Amount range */}
          <div style={S.group}>
            <label style={S.label}>Amount Range (₹)</label>
            <div style={S.range}>
              <input style={{ ...S.input, width: 80 }} type="number" placeholder="Min"
                value={f.amount_min} onChange={e => set("amount_min", e.target.value)} />
              <span style={{ color: "#9CA3AF", fontSize: 12 }}>–</span>
              <input style={{ ...S.input, width: 80 }} type="number" placeholder="Max"
                value={f.amount_max} onChange={e => set("amount_max", e.target.value)} />
            </div>
            {/* Slider — visual only, drives the max field */}
            {(f.amount_max || f.amount_min) && (
              <input type="range" min={0} max={10000000} step={10000}
                value={f.amount_max || 0}
                onChange={e => set("amount_max", e.target.value)}
                style={{ marginTop: 6, accentColor: "#1E3A5F", width: "100%" }}
              />
            )}
            {!f.amount_max && !f.amount_min && (
              <input type="range" min={0} max={10000000} step={10000}
                value={0}
                onChange={e => set("amount_max", e.target.value)}
                style={{ marginTop: 6, accentColor: "#1E3A5F", width: "100%" }}
              />
            )}
          </div>

          {/* Status */}
          <div style={S.group}>
            <label style={S.label}>Status</label>
            <select style={{ ...S.input }}
              value={f.status} onChange={e => set("status", e.target.value)}>
              <option value="">All</option>
              <option value="PASSED">Passed</option>
              <option value="WARNING">Warning</option>
              <option value="FAILED">Failed</option>
              <option value="NEEDS_MANUAL_REVIEW">Needs review</option>
              <option value="PLACEHOLDER">Placeholder</option>
            </select>
          </div>

          {/* Payment status */}
          <div style={S.group}>
            <label style={S.label}>Payment</label>
            <select style={{ ...S.input }}
              value={f.paid} onChange={e => set("paid", e.target.value)}>
              <option value="">All</option>
              <option value="false">Unpaid</option>
              <option value="true">Paid</option>
            </select>
            <label style={{ display: "flex", alignItems: "center", gap: 5, marginTop: 6, fontSize: 12, color: "#374151", cursor: "pointer" }}>
              <input type="checkbox" checked={f.overdue_only}
                onChange={e => set("overdue_only", e.target.checked)} />
              Overdue only
            </label>
          </div>

          {/* Date period */}
          <div style={{ ...S.group, gridColumn: "span 2" }}>
            <label style={S.label}>Invoice Date</label>
            {/* Presets */}
            <div style={{ display: "flex", gap: 5, flexWrap: "wrap", marginBottom: 8 }}>
              {PRESETS.map(p => (
                <button key={p.value}
                  onClick={() => applyPreset(p.value)}
                  style={{
                    ...S.pill,
                    ...(f.date_preset === p.value ? S.pillOn : {}),
                    fontSize: 11, padding: "3px 9px",
                  }}
                >{p.label}</button>
              ))}
              {f.date_preset && (
                <button onClick={() => setF(p => ({ ...p, date_preset: "", date_from: "", date_to: "" }))}
                  style={{ ...S.pill, fontSize: 11, padding: "3px 9px", color: "#DC2626", border: "1px solid #FECACA" }}>
                  Clear
                </button>
              )}
            </div>
            {/* Manual range */}
            <div style={S.range}>
              <div style={S.group}>
                <label style={{ ...S.label, marginBottom: 2 }}>From</label>
                <input type="date" style={S.input}
                  value={f.date_from}
                  onChange={e => { set("date_from", e.target.value); set("date_preset", ""); }} />
              </div>
              <span style={{ color: "#9CA3AF", fontSize: 12, marginTop: 14 }}>–</span>
              <div style={S.group}>
                <label style={{ ...S.label, marginBottom: 2 }}>To</label>
                <input type="date" style={S.input}
                  value={f.date_to}
                  onChange={e => { set("date_to", e.target.value); set("date_preset", ""); }} />
              </div>
            </div>
          </div>

        </div>
      )}
    </div>
  );
}