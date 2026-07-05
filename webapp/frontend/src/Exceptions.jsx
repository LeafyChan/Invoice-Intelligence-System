import { useState, useEffect, useCallback } from "react";

const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000";
const PAGE_SIZE = 50;

const STATUS_META = {
  open:     { label: "Open",     bg: "#FEE2E2", color: "#B91C1C" },
  resolved: { label: "Resolved", bg: "#DCFCE7", color: "#15803D" },
  ignored:  { label: "Ignored",  bg: "#F3F4F6", color: "#6B7280" },
};

const TYPE_META = {
  amount_mismatch:      { label: "Amount mismatch",      bg: "#FFEDD5", color: "#9A3412" },
  po_mismatch:          { label: "PO mismatch",          bg: "#E0E7FF", color: "#3730A3" },
  po_missing:           { label: "PO missing",           bg: "#E0E7FF", color: "#3730A3" },
  grn_quantity_mismatch:{ label: "GRN qty mismatch",     bg: "#FEF9C3", color: "#854D0E" },
  mrn_undisclosed:      { label: "MRN undisclosed",      bg: "#FFEDD5", color: "#9A3412" },
  gstin_mismatch:       { label: "GSTIN mismatch",       bg: "#FEE2E2", color: "#B91C1C" },
  low_confidence:       { label: "Low confidence",       bg: "#F3F4F6", color: "#374151" },
  missing_fields:       { label: "Missing fields",       bg: "#F3F4F6", color: "#374151" },
};

function statusMeta(s) {
  return STATUS_META[s] || { label: s ?? "Unknown", bg: "#F3F4F6", color: "#374151" };
}
function typeMeta(t) {
  return TYPE_META[t] || { label: t ?? "Unknown", bg: "#F3F4F6", color: "#374151" };
}

function Badge({ meta }) {
  return (
    <span style={{
      display: "inline-block", padding: "2px 8px", borderRadius: 4,
      fontSize: 11, fontWeight: 600, letterSpacing: "0.03em",
      background: meta.bg, color: meta.color, whiteSpace: "nowrap",
    }}>
      {meta.label}
    </span>
  );
}

function fmtDatetime(d) {
  if (!d) return "—";
  return new Date(d).toLocaleString("en-IN", {
    day: "2-digit", month: "short", year: "numeric",
    hour: "2-digit", minute: "2-digit",
  });
}

function Spinner() {
  return (
    <div style={{ display: "flex", alignItems: "center", justifyContent: "center", padding: 48, color: "#6B7280" }}>
      <svg width="24" height="24" viewBox="0 0 24 24" fill="none" style={{ animation: "spin 0.8s linear infinite" }}>
        <circle cx="12" cy="12" r="10" stroke="#E5E7EB" strokeWidth="3" />
        <path d="M12 2a10 10 0 0 1 10 10" stroke="#312E81" strokeWidth="3" strokeLinecap="round" />
      </svg>
      <span style={{ marginLeft: 10, fontSize: 13 }}>Loading exceptions…</span>
      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
    </div>
  );
}

function ResolveControls({ exc, getToken, onResolved }) {
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);
  const [editingNote, setEditingNote] = useState(false);

  async function act(status) {
    setSaving(true);
    try {
      const tok = await getToken();
      const res = await fetch(`${API_BASE}/exceptions/${exc.exception_id}`, {
        method: "PATCH",
        headers: { Authorization: `Bearer ${tok}`, "Content-Type": "application/json" },
        body: JSON.stringify({ status, resolution_note: note || undefined }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      onResolved(exc.exception_id, status);
    } catch (e) {
      alert(`Failed to update: ${e}`);
    } finally {
      setSaving(false);
    }
  }

  if (exc.status !== "open") {
    return (
      <div style={{ fontSize: 11, color: "#6B7280" }}>
        {exc.resolution_note || (exc.resolved_by ? "Resolved" : "Auto-resolved")}
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4, minWidth: 200 }}>
      {editingNote ? (
        <input
          autoFocus
          value={note}
          onChange={e => setNote(e.target.value)}
          placeholder="Optional note…"
          style={s.noteInput}
          onBlur={() => !note && setEditingNote(false)}
        />
      ) : (
        <button style={s.addNoteBtn} onClick={() => setEditingNote(true)}>+ note</button>
      )}
      <div style={{ display: "flex", gap: 6 }}>
        <button disabled={saving} onClick={() => act("resolved")} style={s.resolveBtn}>
          {saving ? "…" : "Resolve"}
        </button>
        <button disabled={saving} onClick={() => act("ignored")} style={s.ignoreBtn}>
          Ignore
        </button>
      </div>
    </div>
  );
}

export default function Exceptions({ getToken }) {
  const [data, setData]     = useState(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr]       = useState(null);
  const [status, setStatus] = useState("open");
  const [excType, setExcType] = useState("");
  const [page, setPage]     = useState(1);
  const [checking, setChecking] = useState(false);
  const [checkResult, setCheckResult] = useState(null);

  const fetchExceptions = useCallback(async () => {
    setLoading(true); setErr(null);
    try {
      const tok = await getToken();
      const params = new URLSearchParams({ page, page_size: PAGE_SIZE });
      if (status)  params.set("status", status);
      if (excType) params.set("exception_type", excType);
      const res = await fetch(`${API_BASE}/exceptions?${params}`, {
        headers: { Authorization: `Bearer ${tok}` },
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setData(await res.json());
    } catch (e) { setErr(String(e)); }
    finally { setLoading(false); }
  }, [getToken, status, excType, page]);

  useEffect(() => { fetchExceptions(); }, [fetchExceptions]);

  async function runChecks() {
    setChecking(true); setCheckResult(null);
    try {
      const tok = await getToken();
      const res = await fetch(`${API_BASE}/supply-chain/reconcile`, {
        method: "POST",
        headers: { Authorization: `Bearer ${tok}` },
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const r = await res.json();
      setCheckResult(r);
      setPage(1);
      fetchExceptions();
    } catch (e) { setErr(String(e)); }
    finally { setChecking(false); }
  }

  function handleResolved(exceptionId, newStatus) {
    setData(prev => {
      if (!prev) return prev;
      if (status === "open") {
        return { ...prev, exceptions: prev.exceptions.filter(e => e.exception_id !== exceptionId) };
      }
      return {
        ...prev,
        exceptions: prev.exceptions.map(e =>
          e.exception_id === exceptionId ? { ...e, status: newStatus } : e
        ),
      };
    });
  }

  const totalPages = data?.total_pages ?? 1;

  return (
    <div style={s.root}>
      {/* ── Header ── */}
      <div style={s.header}>
        <div>
          <div style={s.headerTitle}>Exception Queue</div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          {data != null && !loading && (
            <span style={s.countLabel}>
              {data.total_count.toLocaleString("en-IN")} exception{data.total_count !== 1 ? "s" : ""}
            </span>
          )}
          {checkResult && !checking && (
            <span style={{ fontSize: 11, color: "#93C5FD" }}>
              {checkResult.exceptions_written} exception{checkResult.exceptions_written !== 1 ? "s" : ""} written · {checkResult.invoices_checked} invoices checked
            </span>
          )}
          <button onClick={fetchExceptions} disabled={loading} style={s.refreshBtn}>↻ Refresh</button>
          <button onClick={runChecks} disabled={checking} style={s.checkBtn}>
            {checking ? "Checking…" : "▶ Run checks"}
          </button>
        </div>
      </div>

      {/* ── Filter strip ── */}
      <div style={s.filterStrip}>
        <select value={status} onChange={e => { setStatus(e.target.value); setPage(1); }} style={s.select}>
          <option value="open">Open</option>
          <option value="resolved">Resolved</option>
          <option value="ignored">Ignored</option>
          <option value="">All statuses</option>
        </select>
        <select value={excType} onChange={e => { setExcType(e.target.value); setPage(1); }} style={s.select}>
          <option value="">All types</option>
          <option value="amount_mismatch">Amount mismatch</option>
          <option value="po_mismatch">PO mismatch</option>
          <option value="po_missing">PO missing</option>
          <option value="grn_quantity_mismatch">GRN qty mismatch</option>
          <option value="mrn_undisclosed">MRN undisclosed</option>
          <option value="gstin_mismatch">GSTIN mismatch</option>
          <option value="low_confidence">Low confidence</option>
          <option value="missing_fields">Missing fields</option>
        </select>
      </div>

      {/* ── Content ── */}
      <div style={{ flex: 1, overflow: "auto", minWidth: 0 }}>
        {err && (
          <div style={s.errBanner}>
            Failed to load: {err}
            <button onClick={fetchExceptions} style={s.retryBtn}>Retry</button>
          </div>
        )}

        {loading && !data && <Spinner />}

        {!loading && data?.exceptions?.length === 0 && (
          <div style={s.empty}>
            <div style={{ fontSize: 32, marginBottom: 12 }}>✓</div>
            <div style={{ fontWeight: 600, marginBottom: 6 }}>
              {status === "open" ? "No open exceptions" : "Nothing here"}
            </div>
            <div style={{ fontSize: 13, color: "#6B7280" }}>
              {status === "open"
                ? "Exceptions are raised automatically when invoices are scanned or fields are edited. Nothing needs attention right now."
                : "Try adjusting the filters above."}
            </div>
          </div>
        )}

        {data?.exceptions?.length > 0 && (
          <table style={s.table}>
            <thead>
              <tr>
                <th style={s.th}>Type</th>
                <th style={s.th}>Description</th>
                <th style={s.th}>Status</th>
                <th style={s.th}>Raised</th>
                <th style={s.th}>Action</th>
              </tr>
            </thead>
            <tbody>
              {data.exceptions.map((exc, i) => (
                <tr key={exc.exception_id} style={{ background: i % 2 === 0 ? "#fff" : "#F9FAFB" }}>
                  <td style={s.td}><Badge meta={typeMeta(exc.exception_type)} /></td>
                  <td style={{ ...s.td, maxWidth: 440 }}>
                    <div style={{ fontSize: 13, color: "#111318" }}>{exc.description}</div>
                    {exc.detail && (
                      <div style={{ fontSize: 11, color: "#9CA3AF", marginTop: 2, fontFamily: "monospace" }}>
                        {typeof exc.detail === "string" ? exc.detail : JSON.stringify(exc.detail)}
                      </div>
                    )}
                  </td>
                  <td style={s.td}><Badge meta={statusMeta(exc.status)} /></td>
                  <td style={{ ...s.td, whiteSpace: "nowrap", fontSize: 11, color: "#9CA3AF" }}>
                    {fmtDatetime(exc.created_at)}
                  </td>
                  <td style={s.td}>
                    <ResolveControls exc={exc} getToken={getToken} onResolved={handleResolved} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        {data?.total_count > PAGE_SIZE && (
          <div style={s.pagination}>
            <button onClick={() => setPage(p => Math.max(1, p-1))} disabled={page <= 1 || loading}
              style={{ ...s.pageBtn, opacity: page <= 1 ? 0.4 : 1 }}>← Prev</button>
            <span style={{ fontSize: 13, color: "#6B7280" }}>Page {page} of {totalPages}</span>
            <button onClick={() => setPage(p => Math.min(totalPages, p+1))} disabled={page >= totalPages || loading}
              style={{ ...s.pageBtn, opacity: page >= totalPages ? 0.4 : 1 }}>Next →</button>
          </div>
        )}
      </div>
    </div>
  );
}

const s = {
  root:        { display: "flex", flexDirection: "column", height: "100%", overflow: "hidden", background: "#F7F8FA" },
  header:      { display: "flex", alignItems: "flex-start", justifyContent: "space-between", padding: "16px 20px", background: "#1E3A5F", color: "#fff", flexShrink: 0, gap: 12 },
  headerTitle: { fontSize: 16, fontWeight: 700, marginBottom: 4 },
  filterStrip: { display: "flex", alignItems: "center", gap: 10, padding: "10px 20px", borderBottom: "1px solid #E5E7EB", background: "#fff", flexShrink: 0, flexWrap: "wrap" },
  select:      { fontSize: 13, padding: "6px 10px", borderRadius: 6, border: "1px solid #D1D5DB", fontFamily: "inherit", color: "#374151", background: "#fff" },
  countLabel:  { fontSize: 12, color: "#93C5FD", whiteSpace: "nowrap" },
  refreshBtn:  { background: "rgba(255,255,255,0.15)", color: "#fff", border: "none", borderRadius: 6, padding: "6px 12px", fontSize: 12, cursor: "pointer", fontFamily: "inherit" },
  checkBtn:    { background: "#312E81", color: "#fff", border: "none", borderRadius: 6, padding: "6px 14px", fontSize: 12, fontWeight: 600, cursor: "pointer", fontFamily: "inherit" },
  table:       { width: "100%", borderCollapse: "collapse", fontSize: 13 },
  th:          { textAlign: "left", padding: "8px 14px", fontSize: 11, fontWeight: 600, color: "#6B7280", textTransform: "uppercase", letterSpacing: "0.04em", borderBottom: "1px solid #E5E7EB", background: "#F9FAFB", position: "sticky", top: 0 },
  td:          { padding: "10px 14px", verticalAlign: "top", borderBottom: "1px solid #F3F4F6" },
  errBanner:   { margin: 20, padding: "12px 16px", background: "#FEF2F2", border: "1px solid #FECACA", borderRadius: 6, color: "#B91C1C", fontSize: 13, display: "flex", alignItems: "center", gap: 12 },
  retryBtn:    { background: "#B91C1C", color: "#fff", border: "none", borderRadius: 5, padding: "4px 12px", fontSize: 12, cursor: "pointer", fontFamily: "inherit" },
  empty:       { display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", padding: 64, color: "#374151", textAlign: "center" },
  pagination:  { display: "flex", alignItems: "center", justifyContent: "center", gap: 16, padding: "14px 20px", borderTop: "1px solid #E5E7EB", background: "#fff" },
  pageBtn:     { background: "#fff", border: "1px solid #D1D5DB", borderRadius: 6, padding: "5px 14px", fontSize: 13, cursor: "pointer", fontFamily: "inherit", color: "#374151" },
  noteInput:   { fontSize: 11, padding: "3px 6px", borderRadius: 4, border: "1px solid #D1D5DB", fontFamily: "inherit", width: 180 },
  addNoteBtn:  { background: "none", border: "none", color: "#6B7280", fontSize: 11, cursor: "pointer", fontFamily: "inherit", textAlign: "left", padding: 0 },
  resolveBtn:  { background: "#15803D", color: "#fff", border: "none", borderRadius: 4, padding: "4px 10px", fontSize: 12, cursor: "pointer", fontFamily: "inherit", fontWeight: 600 },
  ignoreBtn:   { background: "#fff", color: "#6B7280", border: "1px solid #D1D5DB", borderRadius: 4, padding: "4px 10px", fontSize: 12, cursor: "pointer", fontFamily: "inherit" },
};