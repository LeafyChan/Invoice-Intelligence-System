/**
 * VendorScorecard.jsx
 * ===================
 * Vendor reliability scores computed from GRN + MR + Invoice + PO data.
 * Uses getToken pattern matching the rest of the app.
 */
import { useState, useEffect, useCallback } from "react";

const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000";

const GRADE_META = {
  A: { bg: "#DCFCE7", color: "#15803D", label: "Preferred"           },
  B: { bg: "#DBEAFE", color: "#1D4ED8", label: "Acceptable"          },
  C: { bg: "#FEF9C3", color: "#854D0E", label: "Watch"               },
  D: { bg: "#FFEDD5", color: "#9A3412", label: "Caution"             },
  F: { bg: "#FEE2E2", color: "#B91C1C", label: "Review Relationship" },
};

const FLAG_META = {
  high_rejection_rate:     { label: "High Rejection Rate",     color: "#B91C1C" },
  advance_risk:            { label: "Advance Risk >50%",       color: "#9A3412" },
  logistics_non_compliant: { label: "Logistics Non-Compliant", color: "#9A3412" },
  compliance_risk:         { label: "Compliance Risk",         color: "#B91C1C" },
};

function GradeBadge({ grade }) {
  const m = GRADE_META[grade] || { bg: "#F3F4F6", color: "#374151", label: grade ?? "—" };
  return (
    <span style={{
      display: "inline-block", padding: "2px 10px", borderRadius: 4,
      fontSize: 11, fontWeight: 700, letterSpacing: "0.04em",
      background: m.bg, color: m.color, whiteSpace: "nowrap",
    }}>
      {grade} — {m.label}
    </span>
  );
}

function ScoreBar({ value }) {
  const pct = Math.min(100, Math.max(0, value ?? 0));
  const color = pct >= 85 ? "#16A34A" : pct >= 70 ? "#2563EB" : pct >= 55 ? "#CA8A04" : pct >= 40 ? "#EA580C" : "#DC2626";
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
      <div style={{ flex: 1, height: 6, background: "#E5E7EB", borderRadius: 3, overflow: "hidden" }}>
        <div style={{ width: `${pct}%`, height: "100%", background: color, borderRadius: 3, transition: "width 0.3s" }} />
      </div>
      <span style={{ fontSize: 11, fontWeight: 600, color, minWidth: 28, textAlign: "right" }}>{pct}</span>
    </div>
  );
}

function StatRow({ label, value }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, padding: "4px 0", borderBottom: "1px solid #F3F4F6" }}>
      <span style={{ color: "#6B7280" }}>{label}</span>
      <span style={{ fontWeight: 500, color: "#111318" }}>{value ?? "—"}</span>
    </div>
  );
}

export default function VendorScorecard({ getToken }) {
  const [vendors, setVendors] = useState([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr]         = useState(null);
  const [selected, setSelected] = useState(null);
  const [filter, setFilter]   = useState("all");
  const [recalcId, setRecalcId] = useState(null);

  const fetchScorecard = useCallback(async () => {
    setLoading(true); setErr(null);
    try {
      const tok = await getToken();
      const res = await fetch(`${API_BASE}/vendors/scorecard`, {
        headers: { Authorization: `Bearer ${tok}` },
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setVendors(await res.json());
    } catch (e) {
      setErr(String(e));
    } finally {
      setLoading(false);
    }
  }, [getToken]);

  useEffect(() => { fetchScorecard(); }, [fetchScorecard]);

  async function recalculate(vendor_id, e) {
    e.stopPropagation();
    setRecalcId(vendor_id);
    try {
      const tok = await getToken();
      await fetch(`${API_BASE}/vendors/${vendor_id}/score/recalculate`, {
        method: "POST",
        headers: { Authorization: `Bearer ${tok}` },
      });
      await fetchScorecard();
    } finally {
      setRecalcId(null);
    }
  }

  const filtered = vendors.filter(v => {
    if (filter === "flagged") return v.flags && Object.keys(v.flags || {}).length > 0;
    if (filter === "low")     return (v.score ?? 100) < 55;
    return true;
  });

  const s = styles;

  return (
    <div style={s.root}>
      <div style={s.header}>
        <div>
          <div style={s.title}>Vendor Scorecard</div>
          <div style={s.subtitle}>Scores computed from GRN quality, on-time delivery, invoice accuracy, and transport compliance.</div>
        </div>
        <button onClick={fetchScorecard} disabled={loading} style={s.refreshBtn}>
          {loading ? "Loading…" : "↻ Refresh"}
        </button>
      </div>

      <div style={s.filterStrip}>
        {[["all","All vendors"],["flagged","Flagged only"],["low","Score < 55"]].map(([val, lbl]) => (
          <button key={val} onClick={() => setFilter(val)}
            style={{ ...s.filterBtn, ...(filter === val ? s.filterActive : s.filterInactive) }}>
            {lbl}
          </button>
        ))}
        <span style={{ marginLeft: "auto", fontSize: 12, color: "#6B7280" }}>
          {filtered.length} vendor{filtered.length !== 1 ? "s" : ""}
        </span>
      </div>

      {err && (
        <div style={s.errBanner}>Failed to load: {err} <button onClick={fetchScorecard} style={s.retryBtn}>Retry</button></div>
      )}

      {!loading && vendors.length === 0 && !err && (
        <div style={s.empty}>
          <div style={{ fontSize: 32, marginBottom: 12 }}>🏭</div>
          <div style={{ fontWeight: 600, marginBottom: 6 }}>No vendor scores yet</div>
          <div style={{ fontSize: 13, color: "#6B7280" }}>
            Scores are computed from GRN + Material Return + Invoice data.<br />
            Sync those documents first, then use Recalculate on each vendor.
          </div>
        </div>
      )}

      {filtered.length > 0 && (
        <div style={{ flex: 1, overflow: "auto" }}>
          <table style={s.table}>
            <thead>
              <tr>
                {["Vendor","Score","Grade","Quality","On-Time","Accuracy","Transport","Invoices","GRNs","Returns","Flags",""].map(h => (
                  <th key={h} style={s.th}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filtered.map((v, i) => (
                <tr key={v.vendor_id}
                  onClick={() => setSelected(v.vendor_id === selected?.vendor_id ? null : v)}
                  style={{
                    ...s.row,
                    background: v.vendor_id === selected?.vendor_id ? "#EEF2FF"
                      : i % 2 === 0 ? "#FFFFFF" : "#F9FAFB",
                    cursor: "pointer",
                  }}>
                  <td style={{ ...s.td, fontWeight: 500, maxWidth: 160 }}>{v.vendor_name ?? "—"}</td>
                  <td style={{ ...s.td, width: 120 }}><ScoreBar value={v.score} /></td>
                  <td style={s.td}><GradeBadge grade={v.grade} /></td>
                  <td style={{ ...s.td, fontSize: 11 }}>{v.quality_rate != null ? `${(v.quality_rate*100).toFixed(1)}%` : "—"}</td>
                  <td style={{ ...s.td, fontSize: 11 }}>{v.on_time_rate != null ? `${(v.on_time_rate*100).toFixed(1)}%` : "—"}</td>
                  <td style={{ ...s.td, fontSize: 11 }}>{v.accuracy_rate != null ? `${(v.accuracy_rate*100).toFixed(1)}%` : "—"}</td>
                  <td style={{ ...s.td, fontSize: 11 }}>{v.transport_compliance_rate != null ? `${(v.transport_compliance_rate*100).toFixed(1)}%` : "—"}</td>
                  <td style={{ ...s.td, fontSize: 11, textAlign: "right" }}>{v.total_invoices ?? "—"}</td>
                  <td style={{ ...s.td, fontSize: 11, textAlign: "right" }}>{v.total_grns ?? "—"}</td>
                  <td style={{ ...s.td, fontSize: 11, textAlign: "right" }}>{v.total_returns ?? "—"}</td>
                  <td style={s.td}>
                    {Object.entries(v.flags || {}).filter(([,val]) => val).map(([flag]) => (
                      <div key={flag} style={{ fontSize: 10, color: FLAG_META[flag]?.color ?? "#B91C1C", whiteSpace: "nowrap" }}>
                        ⚠ {FLAG_META[flag]?.label ?? flag}
                      </div>
                    ))}
                  </td>
                  <td style={s.td} onClick={e => recalculate(v.vendor_id, e)}>
                    <button style={s.recalcBtn} disabled={recalcId === v.vendor_id}>
                      {recalcId === v.vendor_id ? "…" : "↻"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {selected && (
        <div style={s.detailOverlay} onClick={() => setSelected(null)}>
          <div style={s.detailPanel} onClick={e => e.stopPropagation()}>
            <div style={s.detailHeader}>
              <div>
                <div style={{ fontWeight: 600, fontSize: 15 }}>{selected.vendor_name}</div>
                {selected.vendor_gstin && <div style={{ fontSize: 11, color: "#6B7280", fontFamily: "monospace" }}>{selected.vendor_gstin}</div>}
              </div>
              <button onClick={() => setSelected(null)} style={s.closeBtn}>✕</button>
            </div>
            <div style={s.detailBody}>
              <div style={{ marginBottom: 16 }}><ScoreBar value={selected.score} /><div style={{ marginTop: 6 }}><GradeBadge grade={selected.grade} /></div></div>
              <StatRow label="Quality rate"         value={selected.quality_rate != null ? `${(selected.quality_rate*100).toFixed(1)}%` : null} />
              <StatRow label="On-time delivery"     value={selected.on_time_rate != null ? `${(selected.on_time_rate*100).toFixed(1)}%` : null} />
              <StatRow label="Invoice accuracy"     value={selected.accuracy_rate != null ? `${(selected.accuracy_rate*100).toFixed(1)}%` : null} />
              <StatRow label="Transport compliance" value={selected.transport_compliance_rate != null ? `${(selected.transport_compliance_rate*100).toFixed(1)}%` : null} />
              <StatRow label="Avg advance %"        value={selected.avg_advance_pct != null ? `${selected.avg_advance_pct.toFixed(1)}%` : null} />
              <StatRow label="Total invoices"       value={selected.total_invoices} />
              <StatRow label="Total GRNs"           value={selected.total_grns} />
              <StatRow label="Total returns"        value={selected.total_returns} />
              {selected.last_calculated_at && (
                <div style={{ fontSize: 10, color: "#9CA3AF", marginTop: 10 }}>
                  Last calculated: {new Date(selected.last_calculated_at).toLocaleString("en-IN")}
                </div>
              )}
              {Object.keys(selected.flags || {}).length > 0 && (
                <div style={{ marginTop: 14 }}>
                  <div style={{ fontSize: 11, fontWeight: 600, color: "#6B7280", textTransform: "uppercase", letterSpacing: "0.04em", marginBottom: 6 }}>Active Flags</div>
                  {Object.entries(selected.flags).filter(([,v]) => v).map(([flag]) => (
                    <div key={flag} style={{ fontSize: 12, color: FLAG_META[flag]?.color ?? "#B91C1C", padding: "3px 0" }}>
                      ⚠ {FLAG_META[flag]?.label ?? flag}
                    </div>
                  ))}
                </div>
              )}
              <button onClick={e => recalculate(selected.vendor_id, e)} style={{ ...s.recalcBtn, marginTop: 16, width: "100%", padding: "8px 0", fontSize: 13 }}>
                {recalcId === selected.vendor_id ? "Recalculating…" : "↻ Recalculate Score"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

const styles = {
  root:        { display: "flex", flexDirection: "column", height: "100%", overflow: "hidden", fontFamily: "Inter, system-ui, sans-serif", background: "#F9FAFB" },
  header:      { display: "flex", alignItems: "flex-start", justifyContent: "space-between", padding: "20px 24px 12px", background: "#fff", borderBottom: "1px solid #E5E7EB" },
  title:       { fontSize: 18, fontWeight: 700, color: "#111318", marginBottom: 4 },
  subtitle:    { fontSize: 12, color: "#6B7280", maxWidth: 500 },
  refreshBtn:  { background: "#312E81", color: "#fff", border: "none", borderRadius: 6, padding: "7px 16px", fontSize: 13, cursor: "pointer", fontFamily: "inherit", flexShrink: 0 },
  filterStrip: { display: "flex", alignItems: "center", gap: 6, padding: "10px 24px", background: "#fff", borderBottom: "1px solid #E5E7EB" },
  filterBtn:   { border: "1px solid #D1D5DB", borderRadius: 6, padding: "4px 12px", fontSize: 12, cursor: "pointer", fontFamily: "inherit" },
  filterActive:   { background: "#312E81", color: "#fff", borderColor: "#312E81" },
  filterInactive: { background: "#fff", color: "#374151" },
  errBanner:   { margin: 20, padding: "12px 16px", background: "#FEF2F2", border: "1px solid #FECACA", borderRadius: 6, color: "#B91C1C", fontSize: 13, display: "flex", alignItems: "center", gap: 12 },
  retryBtn:    { background: "#B91C1C", color: "#fff", border: "none", borderRadius: 5, padding: "4px 12px", fontSize: 12, cursor: "pointer", fontFamily: "inherit" },
  empty:       { display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", padding: 64, color: "#374151", textAlign: "center" },
  table:       { width: "100%", borderCollapse: "collapse", fontSize: 13 },
  th:          { padding: "8px 12px", textAlign: "left", fontSize: 11, fontWeight: 600, color: "#6B7280", textTransform: "uppercase", letterSpacing: "0.04em", borderBottom: "2px solid #E5E7EB", whiteSpace: "nowrap", background: "#F9FAFB" },
  row:         { borderBottom: "1px solid #F3F4F6", transition: "background 0.1s" },
  td:          { padding: "10px 12px", verticalAlign: "middle" },
  recalcBtn:   { background: "#F3F4F6", border: "1px solid #E5E7EB", borderRadius: 5, padding: "3px 10px", fontSize: 12, cursor: "pointer", fontFamily: "inherit", color: "#374151" },
  detailOverlay: { position: "fixed", inset: 0, background: "rgba(0,0,0,0.35)", zIndex: 50, display: "flex", justifyContent: "flex-end" },
  detailPanel:   { background: "#fff", width: 360, height: "100%", display: "flex", flexDirection: "column", boxShadow: "-4px 0 20px rgba(0,0,0,0.12)" },
  detailHeader:  { display: "flex", justifyContent: "space-between", alignItems: "flex-start", padding: "16px", borderBottom: "1px solid #E5E7EB", background: "#F9FAFB" },
  detailBody:    { padding: 16, overflowY: "auto", flex: 1 },
  closeBtn:      { background: "none", border: "none", cursor: "pointer", fontSize: 16, color: "#6B7280", padding: 0 },
};