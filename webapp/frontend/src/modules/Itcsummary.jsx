import { useState, useEffect, useCallback } from "react";

const API_BASE =
  import.meta.env.VITE_API_BASE || import.meta.env.VITE_API_BASE || "";

function formatINR(n) {
  return `₹${Number(n || 0).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

const STATUS_LABEL = {
  expected: "Expected (in HSN profile)",
  ambiguous: "Ambiguous (needs review)",
  manual: "Manually classified",
  unknown: "Unknown (not in HSN profile)",
};
const STATUS_COLOR = {
  expected: "#34d399",
  ambiguous: "#fbbf24",
  manual: "#60a5fa",
  unknown: "#94a3b8",
};

export default function ItcSummary({ getToken }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState(null);
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");

  const fetchSummary = useCallback(async () => {
    setLoading(true);
    setErr(null);
    try {
      const tok = await getToken();
      const params = new URLSearchParams();
      if (dateFrom) params.set("date_from", dateFrom);
      if (dateTo) params.set("date_to", dateTo);
      const res = await fetch(`${API_BASE}/itc-summary?${params}`, {
        headers: { Authorization: `Bearer ${tok}` },
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setData(await res.json());
    } catch (e) {
      setErr(String(e));
    } finally {
      setLoading(false);
    }
  }, [getToken, dateFrom, dateTo]);

  useEffect(() => {
    fetchSummary();
  }, [fetchSummary]);

  const s = styles;
  const maxVendorAmount = data
    ? Math.max(1, ...Object.values(data.by_vendor))
    : 1;
  const totalByStatus = data
    ? Object.values(data.by_hsn_status).reduce((a, b) => a + b, 0)
    : 0;

  return (
    <div style={s.root}>
      <div style={s.header}>
        <div>
          <h2 style={s.heading}>ITC Summary</h2>
          <p style={s.subheading}>
            Total claimable Input Tax Credit across all processed invoices.
          </p>
        </div>
        <div style={s.dateFilters}>
          <input
            type="date"
            value={dateFrom}
            onChange={(e) => setDateFrom(e.target.value)}
            style={s.dateInput}
            aria-label="From date"
          />
          <span style={{ color: "#94a3b8", fontSize: 12 }}>to</span>
          <input
            type="date"
            value={dateTo}
            onChange={(e) => setDateTo(e.target.value)}
            style={s.dateInput}
            aria-label="To date"
          />
          {(dateFrom || dateTo) && (
            <button
              onClick={() => {
                setDateFrom("");
                setDateTo("");
              }}
              style={s.clearDatesBtn}
            >
              Clear
            </button>
          )}
          <button
            onClick={fetchSummary}
            disabled={loading}
            style={s.refreshBtn}
            title="Refresh"
          >
            ↻ Refresh
          </button>
        </div>
      </div>

      {err && (
        <div style={s.errBanner}>
          Failed to load ITC summary: {err}
          <button onClick={fetchSummary} style={s.retryBtn}>
            Retry
          </button>
        </div>
      )}

      {loading && !data && <div style={s.loadingBox}>Loading…</div>}

      {!loading && data && (
        <>
          {/* ── Total card ── */}
          <div style={s.totalCard}>
            <div style={s.totalLabel}>Total claimable ITC</div>
            <div style={s.totalAmount}>
              {formatINR(data.total_claimable_itc)}
            </div>
            <div style={s.totalMeta}>
              Across {data.line_items_counted} line item
              {data.line_items_counted !== 1 ? "s" : ""}
            </div>
            <div style={s.totalNote}>{data.note}</div>
          </div>

          <div style={s.grid}>
            {/* ── By HSN status ── */}
            <div style={s.panel}>
              <div style={s.panelTitle}>By HSN profile status</div>
              {Object.entries(data.by_hsn_status).map(([status, amount]) => {
                const pct =
                  totalByStatus > 0 ? (amount / totalByStatus) * 100 : 0;
                return (
                  <div key={status} style={s.statusRow}>
                    <div style={s.statusRowTop}>
                      <span
                        style={{
                          color: STATUS_COLOR[status],
                          fontWeight: 600,
                          fontSize: 12,
                        }}
                      >
                        {STATUS_LABEL[status]}
                      </span>
                      <span
                        style={{
                          fontSize: 12,
                          fontWeight: 600,
                          color: "#f8fafc",
                        }}
                      >
                        {formatINR(amount)}
                      </span>
                    </div>
                    <div style={s.barTrack}>
                      <div
                        style={{
                          ...s.barFill,
                          width: `${pct}%`,
                          background: STATUS_COLOR[status],
                        }}
                      />
                    </div>
                  </div>
                );
              })}
              {data.by_hsn_status.unknown > 0 && (
                <p style={s.helperNote}>
                  "Unknown" line items have an HSN code not in your saved
                  business profile (Settings → Business profile). Add it there
                  if it's a normal purchase for your business.
                </p>
              )}
            </div>

            {/* ── By vendor ── */}
            <div style={s.panel}>
              <div style={s.panelTitle}>By vendor</div>
              {Object.keys(data.by_vendor).length === 0 ? (
                <p style={s.emptyText}>No data for this period.</p>
              ) : (
                Object.entries(data.by_vendor).map(([vendor, amount]) => (
                  <div key={vendor} style={s.vendorRow}>
                    <div style={s.vendorRowTop}>
                      <span style={s.vendorName} title={vendor}>
                        {vendor}
                      </span>
                      <span style={s.vendorAmount}>{formatINR(amount)}</span>
                    </div>
                    <div style={s.barTrack}>
                      <div
                        style={{
                          ...s.barFill,
                          width: `${(amount / maxVendorAmount) * 100}%`,
                          background: "#6366f1",
                        }}
                      />
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>

          {/* ── Ambiguous lines needing review ── */}
          {data.ambiguous_lines_needing_review.length > 0 && (
            <div style={s.ambiguousPanel}>
              <div style={s.ambiguousTitle}>
                ⚠ {data.ambiguous_lines_needing_review.length} line item(s)
                flagged ambiguous
              </div>
              <p style={s.ambiguousHint}>
                These use an HSN code your business profile marked "watch —
                classify on first use" (e.g. could be raw material or a fixed
                asset depending on how it's actually used). Included in the
                total above, but worth a look.
              </p>
              <table style={s.ambiguousTable}>
                <thead>
                  <tr>
                    <th style={s.ambiguousTh}>HSN code</th>
                    <th style={s.ambiguousTh}>Claimable</th>
                    <th style={s.ambiguousTh}>Invoice</th>
                  </tr>
                </thead>
                <tbody>
                  {data.ambiguous_lines_needing_review.map((row, i) => (
                    <tr key={i}>
                      <td style={s.ambiguousTd}>
                        <code style={{ color: "#fbbf24" }}>
                          {row.hsn_code || "—"}
                        </code>
                      </td>
                      <td style={s.ambiguousTd}>{formatINR(row.claimable)}</td>
                      <td
                        style={{
                          ...s.ambiguousTd,
                          fontSize: 11,
                          color: "#94a3b8",
                        }}
                      >
                        {row.invoice_id}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </div>
  );
}

const styles = {
  root: {
    flex: 1,
    overflow: "auto",
    background: "#020617",
    padding: "28px 24px",
    fontFamily: "Inter, system-ui, -apple-system, sans-serif",
    fontSize: 13,
    color: "#f8fafc",
  },
  header: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "flex-start",
    flexWrap: "wrap",
    gap: 16,
    marginBottom: 24,
  },
  heading: {
    margin: "0 0 4px",
    fontSize: 18,
    fontWeight: 700,
    color: "#ffffff",
    letterSpacing: "-0.025em",
  },
  subheading: {
    margin: 0,
    fontSize: 12,
    color: "#94a3b8",
  },
  dateFilters: {
    display: "flex",
    alignItems: "center",
    gap: 8,
    flexWrap: "wrap",
  },
  dateInput: {
    border: "1px solid #1e293b",
    borderRadius: 8,
    padding: "7px 10px",
    fontSize: 12,
    fontFamily: "inherit",
    background: "#090d16",
    color: "#f8fafc",
    outline: "none",
  },
  clearDatesBtn: {
    background: "none",
    border: "none",
    color: "#94a3b8",
    fontSize: 12,
    cursor: "pointer",
    fontFamily: "inherit",
    textDecoration: "underline",
  },
  refreshBtn: {
    background: "#6366f1",
    border: "none",
    borderRadius: 8,
    color: "#fff",
    fontSize: 13,
    fontWeight: 600,
    padding: "7px 14px",
    cursor: "pointer",
    fontFamily: "inherit",
    whiteSpace: "nowrap",
    boxShadow: "0 4px 12px rgba(99, 102, 241, 0.3)",
    transition: "all 0.15s ease",
  },
  errBanner: {
    background: "rgba(244, 63, 94, 0.1)",
    border: "1px solid rgba(244, 63, 94, 0.3)",
    borderRadius: 8,
    color: "#fda4af",
    padding: "12px 16px",
    marginBottom: 16,
    fontSize: 13,
    display: "flex",
    alignItems: "center",
    gap: 12,
  },
  retryBtn: {
    background: "#f43f5e",
    border: "none",
    borderRadius: 6,
    color: "#fff",
    padding: "4px 12px",
    fontSize: 12,
    cursor: "pointer",
    fontFamily: "inherit",
  },
  loadingBox: {
    color: "#94a3b8",
    fontSize: 13,
    padding: "40px 0",
    textAlign: "center",
  },
  totalCard: {
    background: "linear-gradient(135deg, #1e1b4b 0%, #312e81 100%)",
    border: "1px solid rgba(99, 102, 241, 0.3)",
    borderRadius: 12,
    padding: "24px 28px",
    marginBottom: 20,
    color: "#fff",
    boxShadow: "0 20px 25px -5px rgba(0, 0, 0, 0.5)",
  },
  totalLabel: {
    fontSize: 11,
    fontWeight: 600,
    textTransform: "uppercase",
    letterSpacing: "0.05em",
    color: "rgba(255,255,255,0.7)",
    marginBottom: 6,
  },
  totalAmount: {
    fontSize: 36,
    fontWeight: 700,
    letterSpacing: "-0.02em",
    fontVariantNumeric: "tabular-nums",
    marginBottom: 4,
  },
  totalMeta: {
    fontSize: 12,
    color: "rgba(255,255,255,0.7)",
    marginBottom: 12,
  },
  totalNote: {
    fontSize: 11,
    color: "rgba(255,255,255,0.55)",
    lineHeight: 1.5,
    borderTop: "1px solid rgba(255,255,255,0.15)",
    paddingTop: 10,
  },
  grid: {
    display: "grid",
    gridTemplateColumns: "1fr 1fr",
    gap: 16,
    marginBottom: 20,
  },
  panel: {
    background: "#090d16",
    border: "1px solid #1e293b",
    borderRadius: 12,
    padding: "20px",
    boxShadow: "0 10px 15px -3px rgba(0, 0, 0, 0.5)",
  },
  panelTitle: {
    fontSize: 11,
    fontWeight: 600,
    textTransform: "uppercase",
    letterSpacing: "0.05em",
    color: "#94a3b8",
    marginBottom: 16,
  },
  statusRow: { marginBottom: 16 },
  statusRowTop: {
    display: "flex",
    justifyContent: "space-between",
    marginBottom: 6,
  },
  vendorRow: { marginBottom: 14 },
  vendorRowTop: {
    display: "flex",
    justifyContent: "space-between",
    gap: 10,
    marginBottom: 6,
  },
  vendorName: {
    fontSize: 12,
    color: "#cbd5e1",
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
    flex: 1,
  },
  vendorAmount: {
    fontSize: 12,
    fontWeight: 600,
    color: "#f8fafc",
    whiteSpace: "nowrap",
  },
  barTrack: {
    height: 6,
    background: "#1e293b",
    borderRadius: 3,
    overflow: "hidden",
  },
  barFill: {
    height: "100%",
    borderRadius: 3,
  },
  emptyText: {
    fontSize: 12,
    color: "#94a3b8",
  },
  helperNote: {
    fontSize: 11,
    color: "#94a3b8",
    lineHeight: 1.5,
    marginTop: 14,
    paddingTop: 12,
    borderTop: "1px dashed #1e293b",
  },
  ambiguousPanel: {
    background: "rgba(245, 158, 11, 0.08)",
    border: "1px solid rgba(245, 158, 11, 0.3)",
    borderRadius: 12,
    padding: "20px",
  },
  ambiguousTitle: {
    fontSize: 13,
    fontWeight: 700,
    color: "#fbbf24",
    marginBottom: 6,
  },
  ambiguousHint: {
    margin: "0 0 14px",
    fontSize: 12,
    color: "#fde68a",
    lineHeight: 1.5,
  },
  ambiguousTable: {
    width: "100%",
    borderCollapse: "collapse",
    fontSize: 12,
  },
  ambiguousTh: {
    textAlign: "left",
    padding: "8px 10px",
    fontWeight: 600,
    color: "#fbbf24",
    borderBottom: "1px solid rgba(245, 158, 11, 0.3)",
  },
  ambiguousTd: {
    padding: "8px 10px",
    borderBottom: "1px solid rgba(245, 158, 11, 0.15)",
    color: "#f8fafc",
  },
};
