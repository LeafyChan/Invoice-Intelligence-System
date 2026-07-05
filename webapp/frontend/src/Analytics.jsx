/**
 * Analytics.jsx
 * =============
 * BigQuery-backed analytics tab. Two panels:
 *   1. Monthly ITC trend — line chart from /analytics/itc-trend
 *   2. Vendor reliability — flag-rate table from /analytics/vendor-reliability
 *
 * Both routes return { bq_configured: false } when BQ env vars are missing,
 * which we surface as a friendly setup nudge rather than an error.
 *
 * Props:
 *   getToken — async () => string
 */

import { useState, useEffect, useCallback } from "react";

const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000";

function formatINR(n) {
  return `₹${Number(n || 0).toLocaleString("en-IN", {
    minimumFractionDigits: 0, maximumFractionDigits: 0,
  })}`;
}

// ── Tiny SVG line chart ───────────────────────────────────────────────────────

function LineChart({ data, valueKey = "claimable_itc", labelKey = "month", height = 120 }) {
  if (!data || data.length === 0) return null;
  const vals = data.map(d => Number(d[valueKey]) || 0);
  const max = Math.max(...vals, 1);
  const min = Math.min(...vals, 0);
  const range = max - min || 1;
  const W = 520, H = height;
  const pad = { top: 12, right: 16, bottom: 28, left: 52 };
  const chartW = W - pad.left - pad.right;
  const chartH = H - pad.top - pad.bottom;

  const pts = vals.map((v, i) => [
    pad.left + (i / Math.max(vals.length - 1, 1)) * chartW,
    pad.top + chartH - ((v - min) / range) * chartH,
  ]);

  const pathD = pts.map((p, i) => `${i === 0 ? "M" : "L"}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(" ");
  const areaD = pathD + ` L${pts[pts.length - 1][0].toFixed(1)},${(pad.top + chartH).toFixed(1)} L${pad.left},${(pad.top + chartH).toFixed(1)} Z`;

  // Y-axis ticks
  const yTicks = [0, 0.25, 0.5, 0.75, 1].map(t => ({
    y: pad.top + chartH - t * chartH,
    label: formatINR(min + t * range),
  }));

  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", maxWidth: W, height: "auto", display: "block" }}>
      <defs>
        <linearGradient id="areaGrad" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#312E81" stopOpacity="0.18" />
          <stop offset="100%" stopColor="#312E81" stopOpacity="0.01" />
        </linearGradient>
      </defs>

      {/* Grid lines */}
      {yTicks.map((t, i) => (
        <g key={i}>
          <line x1={pad.left} y1={t.y} x2={W - pad.right} y2={t.y}
            stroke="#F3F4F6" strokeWidth="1" />
          <text x={pad.left - 6} y={t.y + 4} textAnchor="end"
            fontSize="9" fill="#9CA3AF" fontFamily="Inter,system-ui,sans-serif">
            {t.label}
          </text>
        </g>
      ))}

      {/* Area fill */}
      <path d={areaD} fill="url(#areaGrad)" />

      {/* Line */}
      <path d={pathD} fill="none" stroke="#312E81" strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />

      {/* Data points + x-labels */}
      {pts.map((p, i) => (
        <g key={i}>
          <circle cx={p[0]} cy={p[1]} r="3.5" fill="#312E81" />
          <circle cx={p[0]} cy={p[1]} r="6" fill="transparent">
            <title>{data[i][labelKey]}: {formatINR(vals[i])}</title>
          </circle>
          <text x={p[0]} y={pad.top + chartH + 16} textAnchor="middle"
            fontSize="9" fill="#9CA3AF" fontFamily="Inter,system-ui,sans-serif">
            {data[i][labelKey]}
          </text>
        </g>
      ))}
    </svg>
  );
}

// ── Not configured nudge ──────────────────────────────────────────────────────

function BqNudge() {
  return (
    <div style={{
      background: "#F0F0FF", border: "1px solid #C7D2FE", borderRadius: 10,
      padding: "24px 28px", textAlign: "center",
    }}>
      <div style={{ fontSize: 28, marginBottom: 10 }}>📊</div>
      <div style={{ fontSize: 14, fontWeight: 600, color: "#312E81", marginBottom: 6 }}>
        BigQuery not connected
      </div>
      <div style={{ fontSize: 12, color: "#6B7280", lineHeight: 1.7, maxWidth: 340, margin: "0 auto" }}>
        Add <code style={{ background: "#E0E7FF", padding: "1px 5px", borderRadius: 3 }}>BQ_PROJECT_ID</code> and
        {" "}<code style={{ background: "#E0E7FF", padding: "1px 5px", borderRadius: 3 }}>BQ_DATASET</code> to
        your backend <code>.env</code>, then restart. BigQuery syncs automatically on every Drive sync.
      </div>
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

export default function Analytics({ getToken }) {
  const [trend, setTrend]         = useState(null);
  const [vendors, setVendors]     = useState(null);
  const [trendLoading, setTL]     = useState(true);
  const [vendorLoading, setVL]    = useState(true);
  const [trendErr, setTE]         = useState(null);
  const [vendorErr, setVE]        = useState(null);

  const fetchTrend = useCallback(async () => {
    setTL(true); setTE(null);
    try {
      const tok = await getToken();
      const res = await fetch(`${API_BASE}/analytics/itc-trend`, {
        headers: { Authorization: `Bearer ${tok}` },
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setTrend(await res.json());
    } catch (e) { setTE(String(e)); }
    finally { setTL(false); }
  }, [getToken]);

  const fetchVendors = useCallback(async () => {
    setVL(true); setVE(null);
    try {
      const tok = await getToken();
      const res = await fetch(`${API_BASE}/analytics/vendor-reliability`, {
        headers: { Authorization: `Bearer ${tok}` },
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setVendors(await res.json());
    } catch (e) { setVE(String(e)); }
    finally { setVL(false); }
  }, [getToken]);

  useEffect(() => { fetchTrend(); fetchVendors(); }, [fetchTrend, fetchVendors]);

  const bqNotConfigured = (trend && !trend.bq_configured) || (vendors && !vendors.bq_configured);

  return (
    <div style={s.root}>
      <div style={s.header}>
        <div>
          <h2 style={s.heading}>Analytics</h2>
          <p style={s.sub}>BigQuery-powered — monthly ITC trends and vendor risk, fast at any scale.</p>
        </div>
        <button onClick={() => { fetchTrend(); fetchVendors(); }}
          disabled={trendLoading || vendorLoading} style={s.refreshBtn}>
          ↻ Refresh
        </button>
      </div>

      {bqNotConfigured && <BqNudge />}

      {!bqNotConfigured && (
        <div style={s.grid}>

          {/* ITC Trend */}
          <div style={s.card}>
            <div style={s.cardTitle}>Monthly ITC trend</div>
            <div style={s.cardSub}>Claimable Input Tax Credit by month</div>
            {trendLoading && <div style={s.loading}>Loading…</div>}
            {trendErr && <div style={s.err}>{trendErr}</div>}
            {!trendLoading && trend?.months?.length > 0 && (
              <>
                <LineChart data={trend.months} valueKey="claimable_itc" labelKey="month" />
                <div style={s.trendStats}>
                  {trend.months.slice(-3).map(m => (
                    <div key={m.month} style={s.trendStat}>
                      <div style={s.trendStatLabel}>{m.month}</div>
                      <div style={s.trendStatVal}>{formatINR(m.claimable_itc)}</div>
                      <div style={s.trendStatMeta}>{m.line_items} lines · {m.unique_vendors} vendors</div>
                    </div>
                  ))}
                </div>
              </>
            )}
            {!trendLoading && trend?.months?.length === 0 && (
              <div style={s.empty}>No data yet. Run a Drive sync to populate BigQuery.</div>
            )}
          </div>

          {/* Vendor reliability */}
          <div style={s.card}>
            <div style={s.cardTitle}>Vendor reliability</div>
            <div style={s.cardSub}>Flag rate and ITC by vendor — sorted by highest risk first</div>
            {vendorLoading && <div style={s.loading}>Loading…</div>}
            {vendorErr && <div style={s.err}>{vendorErr}</div>}
            {!vendorLoading && vendors?.vendors?.length > 0 && (
              <div style={{ overflowX: "auto" }}>
                <table style={s.table}>
                  <thead>
                    <tr>
                      {["Vendor", "Invoices", "Flagged", "Flag rate", "ITC claimable"].map(h => (
                        <th key={h} style={s.th}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {vendors.vendors.map((v, i) => {
                      const flagRate = v.flag_rate_pct || 0;
                      const riskColor = flagRate > 30 ? "#B91C1C" : flagRate > 10 ? "#854D0E" : "#15803D";
                      const riskBg   = flagRate > 30 ? "#FEE2E2" : flagRate > 10 ? "#FEF9C3" : "#DCFCE7";
                      return (
                        <tr key={i} style={{ borderBottom: "1px solid #F3F4F6" }}>
                          <td style={s.td}>
                            <div style={{ fontWeight: 500, color: "#111318", fontSize: 12 }}>{v.vendor}</div>
                            {v.vendor_gstin && (
                              <div style={{ fontSize: 10, color: "#9CA3AF", fontFamily: "monospace" }}>{v.vendor_gstin}</div>
                            )}
                          </td>
                          <td style={{ ...s.td, textAlign: "center" }}>{v.total_invoices}</td>
                          <td style={{ ...s.td, textAlign: "center" }}>{v.flagged_invoices}</td>
                          <td style={{ ...s.td, textAlign: "center" }}>
                            <span style={{
                              background: riskBg, color: riskColor,
                              fontSize: 11, fontWeight: 700, padding: "2px 7px",
                              borderRadius: 4, whiteSpace: "nowrap",
                            }}>
                              {flagRate.toFixed(1)}%
                            </span>
                          </td>
                          <td style={{ ...s.td, textAlign: "right", fontWeight: 600, fontSize: 12 }}>
                            {formatINR(v.total_claimable_itc)}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
            {!vendorLoading && vendors?.vendors?.length === 0 && (
              <div style={s.empty}>No vendor data yet.</div>
            )}
          </div>

        </div>
      )}
    </div>
  );
}

const s = {
  root: {
    flex: 1, overflow: "auto", background: "#F7F8FA",
    padding: "28px 24px",
    fontFamily: "Inter, system-ui, -apple-system, sans-serif",
    fontSize: 13, color: "#111318",
  },
  header: {
    display: "flex", justifyContent: "space-between", alignItems: "flex-start",
    flexWrap: "wrap", gap: 16, marginBottom: 24,
  },
  heading: { margin: "0 0 4px", fontSize: 18, fontWeight: 700, color: "#111318", letterSpacing: "-0.01em" },
  sub: { margin: 0, fontSize: 13, color: "#6B7280" },
  refreshBtn: {
    background: "#fff", border: "1px solid #312E81", borderRadius: 6,
    color: "#312E81", fontSize: 12, fontWeight: 500, padding: "6px 12px",
    cursor: "pointer", fontFamily: "inherit",
  },
  grid: { display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 },
  card: {
    background: "#fff", border: "1px solid #E5E7EB", borderRadius: 12,
    padding: "20px 22px",
  },
  cardTitle: { fontSize: 14, fontWeight: 700, color: "#111318", marginBottom: 2 },
  cardSub: { fontSize: 11, color: "#9CA3AF", marginBottom: 16 },
  loading: { color: "#9CA3AF", fontSize: 12, padding: "24px 0", textAlign: "center" },
  err: { color: "#B91C1C", fontSize: 12, padding: "12px 0" },
  empty: { color: "#9CA3AF", fontSize: 12, padding: "32px 0", textAlign: "center" },
  trendStats: { display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 12, marginTop: 16 },
  trendStat: {
    background: "#F7F8FA", borderRadius: 8, padding: "10px 12px",
  },
  trendStatLabel: { fontSize: 10, color: "#9CA3AF", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.04em", marginBottom: 3 },
  trendStatVal: { fontSize: 15, fontWeight: 700, color: "#312E81", marginBottom: 2 },
  trendStatMeta: { fontSize: 10, color: "#9CA3AF" },
  table: { width: "100%", borderCollapse: "collapse" },
  th: {
    textAlign: "left", padding: "6px 10px", fontSize: 10, fontWeight: 700,
    textTransform: "uppercase", letterSpacing: "0.05em", color: "#9CA3AF",
    borderBottom: "2px solid #F3F4F6",
  },
  td: { padding: "10px 10px", verticalAlign: "middle" },
};