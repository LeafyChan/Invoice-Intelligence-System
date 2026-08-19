import { useState, useEffect, useCallback } from "react";

const API_BASE =
  import.meta.env.VITE_API_BASE || import.meta.env.VITE_API_BASE || "";

const GRADE_META = {
  A: { bg: "rgba(16, 185, 129, 0.1)", color: "#34d399", label: "Preferred" },
  B: { bg: "rgba(59, 130, 246, 0.1)", color: "#60a5fa", label: "Acceptable" },
  C: { bg: "rgba(245, 158, 11, 0.1)", color: "#fbbf24", label: "Watch" },
  D: { bg: "rgba(249, 115, 22, 0.1)", color: "#fb923c", label: "Caution" },
  F: {
    bg: "rgba(244, 63, 94, 0.1)",
    color: "#f43f5e",
    label: "Review Relationship",
  },
};

const FLAG_META = {
  high_rejection_rate: { label: "High Rejection Rate", color: "#f43f5e" },
  advance_risk: { label: "Advance Risk >50%", color: "#fb923c" },
  logistics_non_compliant: {
    label: "Logistics Non-Compliant",
    color: "#fb923c",
  },
  compliance_risk: { label: "Compliance Risk", color: "#f43f5e" },
};

function GradeBadge({ grade }) {
  const m = GRADE_META[grade] || {
    bg: "rgba(100, 116, 139, 0.1)",
    color: "#94a3b8",
    label: grade ?? "—",
  };
  return (
    <span
      style={{
        display: "inline-block",
        padding: "2px 10px",
        borderRadius: "9999px",
        fontSize: 11,
        fontWeight: 700,
        letterSpacing: "0.04em",
        background: m.bg,
        color: m.color,
        whiteSpace: "nowrap",
        border: `1px solid ${m.color}33`,
      }}
    >
      {grade} — {m.label}
    </span>
  );
}

function ScoreBar({ value }) {
  const pct = Math.min(100, Math.max(0, value ?? 0));
  const color =
    pct >= 85
      ? "#34d399"
      : pct >= 70
        ? "#60a5fa"
        : pct >= 55
          ? "#fbbf24"
          : pct >= 40
            ? "#fb923c"
            : "#f43f5e";
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
      <div
        style={{
          flex: 1,
          height: 6,
          background: "#1e293b",
          borderRadius: 3,
          overflow: "hidden",
        }}
      >
        <div
          style={{
            width: `${pct}%`,
            height: "100%",
            background: color,
            borderRadius: 3,
            transition: "width 0.3s",
          }}
        />
      </div>
      <span
        style={{
          fontSize: 11,
          fontWeight: 600,
          color,
          minWidth: 28,
          textAlign: "right",
        }}
      >
        {pct}
      </span>
    </div>
  );
}

function StatRow({ label, value }) {
  return (
    <div
      style={{
        display: "flex",
        justifyContent: "space-between",
        fontSize: 12,
        padding: "8px 0",
        borderBottom: "1px solid rgba(30, 41, 59, 0.5)",
      }}
    >
      <span style={{ color: "#94a3b8" }}>{label}</span>
      <span style={{ fontWeight: 500, color: "#f8fafc" }}>{value ?? "—"}</span>
    </div>
  );
}

export default function VendorScorecard({ getToken }) {
  const [vendors, setVendors] = useState([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState(null);
  const [selected, setSelected] = useState(null);
  const [filter, setFilter] = useState("all");
  const [recalcId, setRecalcId] = useState(null);

  const fetchScorecard = useCallback(async () => {
    setLoading(true);
    setErr(null);
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

  useEffect(() => {
    fetchScorecard();
  }, [fetchScorecard]);

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

  const filtered = vendors.filter((v) => {
    if (filter === "flagged")
      return v.flags && Object.keys(v.flags || {}).length > 0;
    if (filter === "low") return (v.score ?? 100) < 55;
    return true;
  });

  const s = styles;

  return (
    <div style={s.root}>
      <div style={s.header}>
        <div>
          <div style={s.title}>Vendor Scorecard</div>
          <div style={s.subtitle}>
            Scores computed from GRN quality, on-time delivery, invoice
            accuracy, and transport compliance.
          </div>
        </div>
        <button
          onClick={fetchScorecard}
          disabled={loading}
          style={s.refreshBtn}
        >
          {loading ? "Loading…" : "↻ Refresh"}
        </button>
      </div>

      <div style={s.filterStrip}>
        {[
          ["all", "All vendors"],
          ["flagged", "Flagged only"],
          ["low", "Score < 55"],
        ].map(([val, lbl]) => (
          <button
            key={val}
            onClick={() => setFilter(val)}
            style={{
              ...s.filterBtn,
              ...(filter === val ? s.filterActive : s.filterInactive),
            }}
          >
            {lbl}
          </button>
        ))}
        <span style={{ marginLeft: "auto", fontSize: 12, color: "#94a3b8" }}>
          {filtered.length} vendor{filtered.length !== 1 ? "s" : ""}
        </span>
      </div>

      {err && (
        <div style={s.errBanner}>
          Failed to load: {err}{" "}
          <button onClick={fetchScorecard} style={s.retryBtn}>
            Retry
          </button>
        </div>
      )}

      {!loading && vendors.length === 0 && !err && (
        <div style={s.empty}>
          <div style={{ fontSize: 32, marginBottom: 12 }}>🏭</div>
          <div style={{ fontWeight: 600, marginBottom: 6, color: "#f8fafc" }}>
            No vendor scores yet
          </div>
          <div style={{ fontSize: 13, color: "#94a3b8" }}>
            Scores are computed from GRN + Material Return + Invoice data.
            <br />
            Sync those documents first, then use Recalculate on each vendor.
          </div>
        </div>
      )}

      {filtered.length > 0 && (
        <div style={{ flex: 1, overflow: "auto", background: "#090d16" }}>
          <table style={s.table}>
            <thead>
              <tr>
                {[
                  "Vendor",
                  "Score",
                  "Grade",
                  "Quality",
                  "On-Time",
                  "Accuracy",
                  "Transport",
                  "Invoices",
                  "GRNs",
                  "Returns",
                  "Flags",
                  "",
                ].map((h) => (
                  <th key={h} style={s.th}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filtered.map((v) => (
                <tr
                  key={v.vendor_id}
                  onClick={() =>
                    setSelected(v.vendor_id === selected?.vendor_id ? null : v)
                  }
                  style={{
                    ...s.row,
                    background:
                      v.vendor_id === selected?.vendor_id
                        ? "rgba(99, 102, 241, 0.1)"
                        : "transparent",
                    cursor: "pointer",
                  }}
                  onMouseEnter={(e) => {
                    if (v.vendor_id !== selected?.vendor_id)
                      e.currentTarget.style.background = "#0f172a";
                  }}
                  onMouseLeave={(e) => {
                    if (v.vendor_id !== selected?.vendor_id)
                      e.currentTarget.style.background = "transparent";
                  }}
                >
                  <td
                    style={{
                      ...s.td,
                      fontWeight: 500,
                      maxWidth: 160,
                      color: "#f8fafc",
                    }}
                  >
                    {v.vendor_name ?? "—"}
                  </td>
                  <td style={{ ...s.td, width: 120 }}>
                    <ScoreBar value={v.score} />
                  </td>
                  <td style={s.td}>
                    <GradeBadge grade={v.grade} />
                  </td>
                  <td style={{ ...s.td, fontSize: 11, color: "#cbd5e1" }}>
                    {v.quality_rate != null
                      ? `${(v.quality_rate * 100).toFixed(1)}%`
                      : "—"}
                  </td>
                  <td style={{ ...s.td, fontSize: 11, color: "#cbd5e1" }}>
                    {v.on_time_rate != null
                      ? `${(v.on_time_rate * 100).toFixed(1)}%`
                      : "—"}
                  </td>
                  <td style={{ ...s.td, fontSize: 11, color: "#cbd5e1" }}>
                    {v.accuracy_rate != null
                      ? `${(v.accuracy_rate * 100).toFixed(1)}%`
                      : "—"}
                  </td>
                  <td style={{ ...s.td, fontSize: 11, color: "#cbd5e1" }}>
                    {v.transport_compliance_rate != null
                      ? `${(v.transport_compliance_rate * 100).toFixed(1)}%`
                      : "—"}
                  </td>
                  <td
                    style={{
                      ...s.td,
                      fontSize: 11,
                      textAlign: "right",
                      color: "#cbd5e1",
                    }}
                  >
                    {v.total_invoices ?? "—"}
                  </td>
                  <td
                    style={{
                      ...s.td,
                      fontSize: 11,
                      textAlign: "right",
                      color: "#cbd5e1",
                    }}
                  >
                    {v.total_grns ?? "—"}
                  </td>
                  <td
                    style={{
                      ...s.td,
                      fontSize: 11,
                      textAlign: "right",
                      color: "#cbd5e1",
                    }}
                  >
                    {v.total_returns ?? "—"}
                  </td>
                  <td style={s.td}>
                    {Object.entries(v.flags || {})
                      .filter(([, val]) => val)
                      .map(([flag]) => (
                        <div
                          key={flag}
                          style={{
                            fontSize: 10,
                            color: FLAG_META[flag]?.color ?? "#f43f5e",
                            whiteSpace: "nowrap",
                          }}
                        >
                          ⚠ {FLAG_META[flag]?.label ?? flag}
                        </div>
                      ))}
                  </td>
                  <td style={s.td} onClick={(e) => recalculate(v.vendor_id, e)}>
                    <button
                      style={s.recalcBtn}
                      disabled={recalcId === v.vendor_id}
                    >
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
          <div style={s.detailPanel} onClick={(e) => e.stopPropagation()}>
            <div style={s.detailHeader}>
              <div>
                <div
                  style={{ fontWeight: 600, fontSize: 15, color: "#f8fafc" }}
                >
                  {selected.vendor_name}
                </div>
                {selected.vendor_gstin && (
                  <div
                    style={{
                      fontSize: 11,
                      color: "#94a3b8",
                      fontFamily: "monospace",
                    }}
                  >
                    {selected.vendor_gstin}
                  </div>
                )}
              </div>
              <button onClick={() => setSelected(null)} style={s.closeBtn}>
                ✕
              </button>
            </div>
            <div style={s.detailBody}>
              <div style={{ marginBottom: 16 }}>
                <ScoreBar value={selected.score} />
                <div style={{ marginTop: 8 }}>
                  <GradeBadge grade={selected.grade} />
                </div>
              </div>
              <StatRow
                label="Quality rate"
                value={
                  selected.quality_rate != null
                    ? `${(selected.quality_rate * 100).toFixed(1)}%`
                    : null
                }
              />
              <StatRow
                label="On-time delivery"
                value={
                  selected.on_time_rate != null
                    ? `${(selected.on_time_rate * 100).toFixed(1)}%`
                    : null
                }
              />
              <StatRow
                label="Invoice accuracy"
                value={
                  selected.accuracy_rate != null
                    ? `${(selected.accuracy_rate * 100).toFixed(1)}%`
                    : null
                }
              />
              <StatRow
                label="Transport compliance"
                value={
                  selected.transport_compliance_rate != null
                    ? `${(selected.transport_compliance_rate * 100).toFixed(1)}%`
                    : null
                }
              />
              <StatRow
                label="Avg advance %"
                value={
                  selected.avg_advance_pct != null
                    ? `${selected.avg_advance_pct.toFixed(1)}%`
                    : null
                }
              />
              <StatRow label="Total invoices" value={selected.total_invoices} />
              <StatRow label="Total GRNs" value={selected.total_grns} />
              <StatRow label="Total returns" value={selected.total_returns} />
              {selected.last_calculated_at && (
                <div style={{ fontSize: 10, color: "#64748b", marginTop: 10 }}>
                  Last calculated:{" "}
                  {new Date(selected.last_calculated_at).toLocaleString(
                    "en-IN",
                  )}
                </div>
              )}
              {Object.keys(selected.flags || {}).length > 0 && (
                <div style={{ marginTop: 14 }}>
                  <div
                    style={{
                      fontSize: 11,
                      fontWeight: 600,
                      color: "#94a3b8",
                      textTransform: "uppercase",
                      letterSpacing: "0.04em",
                      marginBottom: 6,
                    }}
                  >
                    Active Flags
                  </div>
                  {Object.entries(selected.flags)
                    .filter(([, v]) => v)
                    .map(([flag]) => (
                      <div
                        key={flag}
                        style={{
                          fontSize: 12,
                          color: FLAG_META[flag]?.color ?? "#f43f5e",
                          padding: "3px 0",
                        }}
                      >
                        ⚠ {FLAG_META[flag]?.label ?? flag}
                      </div>
                    ))}
                </div>
              )}
              <button
                onClick={(e) => recalculate(selected.vendor_id, e)}
                style={{
                  ...s.recalcBtn,
                  marginTop: 16,
                  width: "100%",
                  padding: "8px 0",
                  fontSize: 13,
                  background: "#6366f1",
                  color: "#fff",
                  border: "none",
                }}
              >
                {recalcId === selected.vendor_id
                  ? "Recalculating…"
                  : "↻ Recalculate Score"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

const styles = {
  root: {
    display: "flex",
    flexDirection: "column",
    height: "100%",
    overflow: "hidden",
    fontFamily: "Inter, system-ui, sans-serif",
    background: "#020617",
    color: "#f8fafc",
  },
  header: {
    display: "flex",
    alignItems: "flex-start",
    justifyContent: "space-between",
    padding: "20px 24px 12px",
    background: "rgba(9, 13, 22, 0.75)",
    backdropFilter: "blur(12px)",
    borderBottom: "1px solid #1e293b",
  },
  title: {
    fontSize: 18,
    fontWeight: 700,
    color: "#ffffff",
    marginBottom: 4,
    letterSpacing: "-0.025em",
  },
  subtitle: { fontSize: 12, color: "#94a3b8", maxWidth: 500 },
  refreshBtn: {
    background: "#6366f1",
    color: "#fff",
    border: "none",
    borderRadius: 8,
    padding: "7px 16px",
    fontSize: 13,
    cursor: "pointer",
    fontFamily: "inherit",
    flexShrink: 0,
    boxShadow: "0 4px 12px rgba(99, 102, 241, 0.3)",
  },
  filterStrip: {
    display: "flex",
    alignItems: "center",
    gap: 6,
    padding: "12px 24px",
    background: "rgba(9, 13, 22, 0.6)",
    borderBottom: "1px solid #1e293b",
  },
  filterBtn: {
    border: "1px solid #1e293b",
    borderRadius: 6,
    padding: "5px 12px",
    fontSize: 12,
    cursor: "pointer",
    fontFamily: "inherit",
    transition: "all 0.15s ease",
  },
  filterActive: {
    background: "#6366f1",
    color: "#fff",
    borderColor: "#6366f1",
    boxShadow: "0 2px 8px rgba(99, 102, 241, 0.3)",
  },
  filterInactive: { background: "#090d16", color: "#cbd5e1" },
  errBanner: {
    margin: 20,
    padding: "12px 16px",
    background: "rgba(244, 63, 94, 0.1)",
    border: "1px solid rgba(244, 63, 94, 0.3)",
    borderRadius: 8,
    color: "#fda4af",
    fontSize: 13,
    display: "flex",
    alignItems: "center",
    gap: 12,
  },
  retryBtn: {
    background: "#f43f5e",
    color: "#fff",
    border: "none",
    borderRadius: 5,
    padding: "4px 12px",
    fontSize: 12,
    cursor: "pointer",
    fontFamily: "inherit",
  },
  empty: {
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    justifyContent: "center",
    padding: 64,
    color: "#94a3b8",
    textAlign: "center",
  },
  table: { width: "100%", borderCollapse: "collapse", fontSize: 13 },
  th: {
    padding: "12px 16px",
    textAlign: "left",
    fontSize: 11,
    fontWeight: 500,
    color: "#94a3b8",
    textTransform: "uppercase",
    letterSpacing: "0.05em",
    borderBottom: "1px solid #1e293b",
    whiteSpace: "nowrap",
    background: "rgba(9, 13, 22, 0.8)",
    position: "sticky",
    top: 0,
    zIndex: 1,
  },
  row: {
    borderBottom: "1px solid rgba(30, 41, 59, 0.5)",
    transition: "background 0.1s",
  },
  td: { padding: "14px 16px", verticalAlign: "middle" },
  recalcBtn: {
    background: "#0f172a",
    border: "1px solid #1e293b",
    borderRadius: 6,
    padding: "4px 10px",
    fontSize: 12,
    cursor: "pointer",
    fontFamily: "inherit",
    color: "#cbd5e1",
    transition: "all 0.15s ease",
  },
  detailOverlay: {
    position: "fixed",
    inset: 0,
    background: "rgba(0,0,0,0.7)",
    backdropFilter: "blur(4px)",
    zIndex: 50,
    display: "flex",
    justifyContent: "flex-end",
  },
  detailPanel: {
    background: "#090d16",
    width: 380,
    height: "100%",
    display: "flex",
    flexDirection: "column",
    boxShadow: "-10px 0 25px -5px rgba(0,0,0,0.8)",
    borderLeft: "1px solid #1e293b",
  },
  detailHeader: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "flex-start",
    padding: "20px 24px",
    borderBottom: "1px solid #1e293b",
    background: "rgba(9, 13, 22, 0.8)",
  },
  detailBody: { padding: 24, overflowY: "auto", flex: 1 },
  closeBtn: {
    background: "#1e293b",
    border: "none",
    borderRadius: 6,
    width: 28,
    height: 28,
    cursor: "pointer",
    fontSize: 14,
    color: "#cbd5e1",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
  },
};
