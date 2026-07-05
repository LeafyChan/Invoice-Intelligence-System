// InvoiceList.jsx — S20
// Fixes vs S19:
//   1. Modal props corrected: invoiceId + data + getToken (not invoice={...})
//   2. setReviewInv / setVerifyInv: waits for detail fetch before opening, falls back to inv
//   3. Rescan queue: side panel shows rescan buttons for ALL linked doc files (PO/Waybill/GRN/MRN/Invoice)
//   4. Verify button: always visible (not gated on shouldAutoReview)
//   5. Checkbox: uses any available drive file id (invoice or linked doc) so placeholders can be queued

import { useState, useEffect, useCallback } from "react";
import { useAuth } from "@clerk/clerk-react";
import ReviewModal from "./ReviewModal";
import VerifyModal from "./VerifyModal";

const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000";

// ── Formatters ────────────────────────────────────────────────────────────────

function fmtAmount(v) {
  if (v == null) return "—";
  return new Intl.NumberFormat("en-IN", {
    style: "currency", currency: "INR", maximumFractionDigits: 0,
  }).format(v);
}

function fmtDate(v) {
  if (!v) return "—";
  try {
    return new Date(v).toLocaleDateString("en-IN", {
      day: "2-digit", month: "short", year: "numeric",
    });
  } catch { return v; }
}

function fmtConf(v) {
  if (v == null) return "—";
  // stored 0.0–1.0; guard against already-percent values stored by old code
  const pct = v > 1 ? v : v * 100;
  return `${Math.round(pct)}%`;
}

// ── Pay-by ────────────────────────────────────────────────────────────────────

function computePayBy(inv) {
  const terms = (inv.payment_terms || inv.po_payment_terms || "").trim();
  const invoiceDate = inv.invoice_date ? new Date(inv.invoice_date) : null;
  const grnDate     = inv.grn_date     ? new Date(inv.grn_date)     : null;
  if (!terms) return null;
  const lower = terms.toLowerCase();

  if (/\b(cod|cash on delivery|immediate|due on delivery|on delivery)\b/.test(lower))
    return { label: "On delivery", type: "on_delivery" };

  const dueDateMatch = lower.match(/(?:due\s*(?:date)?[:\s]+|payment\s+due\s+)(\d{1,2}[-/]\d{1,2}[-/]\d{2,4})/);
  if (dueDateMatch) {
    const parsed = new Date(dueDateMatch[1].replace(/[-/]/g, "-"));
    if (!isNaN(parsed)) return { date: parsed, type: "explicit" };
  }

  const grnMatch = lower.match(/(\d+)\s*days?\s*(?:from|after)\s*(?:grn|receipt|delivery)/);
  if (grnMatch) {
    const base = grnDate || invoiceDate;
    if (base) {
      const d = new Date(base);
      d.setDate(d.getDate() + parseInt(grnMatch[1], 10));
      return { date: d, type: "from_grn" };
    }
  }

  const eomMatch = lower.match(/net\s*(\d+)\s*eom/);
  if (eomMatch && invoiceDate) {
    const d = new Date(invoiceDate);
    d.setDate(d.getDate() + parseInt(eomMatch[1], 10));
    d.setMonth(d.getMonth() + 1, 0);
    return { date: d, type: "net_eom" };
  }

  const advMatch = lower.match(/(\d+)%?\s*advance.*?net\s*(\d+)/);
  if (advMatch && invoiceDate) {
    const d = new Date(invoiceDate);
    d.setDate(d.getDate() + parseInt(advMatch[2], 10));
    return { date: d, type: "advance_balance", advance_pct: parseInt(advMatch[1]) };
  }

  const netMatch = lower.match(/(?:net\s*|within\s+)?(\d+)\s*days?/);
  if (netMatch && invoiceDate) {
    const d = new Date(invoiceDate);
    d.setDate(d.getDate() + parseInt(netMatch[1], 10));
    return { date: d, type: "net_days" };
  }

  return { type: "unknown", raw: terms };
}

function PayByCell({ inv }) {
  const pb = computePayBy(inv);
  if (!pb) return <span style={{ color: "#9CA3AF" }}>—</span>;
  if (pb.type === "on_delivery")
    return <span style={{ background:"#DBEAFE",color:"#1D4ED8",borderRadius:4,padding:"1px 6px",fontSize:11,fontWeight:500 }}>On delivery</span>;
  if (pb.type === "unknown")
    return <span style={{ color:"#9CA3AF",fontSize:11 }} title={pb.raw}>—</span>;

  const today = new Date();
  const diff  = pb.date ? Math.ceil((pb.date - today) / 86400000) : null;
  let color = "#6B7280", bg = "transparent";
  let label = pb.date ? fmtDate(pb.date.toISOString()) : "—";
  if (diff !== null) {
    if (diff < 0)       { color="#DC2626"; bg="#FEF2F2"; label=`Overdue ${fmtDate(pb.date.toISOString())}`; }
    else if (diff <= 7) { color="#D97706"; bg="#FFFBEB"; }
  }
  if (pb.type === "advance_balance") label = `${pb.advance_pct}% adv · ${label}`;
  return <span style={{ fontSize:11,color,background:bg,borderRadius:4,padding:bg!=="transparent"?"1px 5px":0 }}>{label}</span>;
}

// ── HSN eligibility (side panel only) ────────────────────────────────────────

function getHsnEligibility(code, profile) {
  if (!code || !profile) return { status: "unknown", reason: "No HSN profile loaded" };
  const c = String(code).trim();

  if (profile.expected_hsn_codes?.some(p => p.code === c))
    return { status: "eligible", reason: "Exact match — expected business purchase" };

  if (profile.ambiguous_hsn_codes?.some(p => p.code === c))
    return { status: "review", reason: "Ambiguous code — verify before claiming ITC" };

  // 6-digit → try 4-digit prefix, then 2-digit chapter
  if (c.length >= 4) {
    const pfx4 = c.slice(0, 4);
    if (profile.expected_hsn_codes?.some(p => p.code.startsWith(pfx4)) ||
        profile.ambiguous_hsn_codes?.some(p => p.code.startsWith(pfx4)))
      return { status: "chapter", reason: `4-digit heading ${pfx4} matches your profile but exact code ${c} is not listed. Flag and verify before claiming ITC.` };
  }

  const ch = c.slice(0, 2);
  if (profile.expected_hsn_codes?.some(p => p.code.startsWith(ch)) ||
      profile.ambiguous_hsn_codes?.some(p => p.code.startsWith(ch)))
    return { status: "chapter", reason: `Chapter ${ch} matches your profile but exact code ${c} is not listed. Flag and verify before claiming ITC.` };

  return { status: "unknown", reason: `Code ${c} not in your HSN profile — ITC likely ineligible` };
}

const HSN_BADGE = {
  eligible: { bg:"#D1FAE5", color:"#065F46", text:"✓" },
  review:   { bg:"#FEF3C7", color:"#92400E", text:"?" },
  chapter:  { bg:"#FFF7ED", color:"#C2410C", text:"⚠" },
  unknown:  { bg:"#F3F4F6", color:"#6B7280", text:"—" },
};

// ── Status badge ──────────────────────────────────────────────────────────────

const STATUS_STYLES = {
  PASSED:             { label:"Passed",       bg:"#D1FAE5", color:"#065F46" },
  WARNING:            { label:"Warning",      bg:"#FEF3C7", color:"#92400E" },
  FAILED:             { label:"Failed",       bg:"#FEE2E2", color:"#991B1B" },
  NEEDS_MANUAL_REVIEW:{ label:"Needs review", bg:"#E0E7FF", color:"#3730A3" },
  PLACEHOLDER:        { label:"Placeholder",  bg:"#F0FDF4", color:"#15803D" },
};

function StatusBadge({ status }) {
  const st = STATUS_STYLES[status] || { label:status||"Unknown", bg:"#F3F4F6", color:"#374151" };
  return <span style={{ background:st.bg,color:st.color,borderRadius:4,padding:"2px 8px",fontSize:11,fontWeight:600,whiteSpace:"nowrap" }}>{st.label}</span>;
}

// ── PWGM badge ────────────────────────────────────────────────────────────────
// Dark = actual Drive file scanned. Light = not scanned. Click opens the file.

function DocChainBadge({ inv }) {
  const docs = [
    { key:"P", label:"Purchase Order",  fileId: inv.po_drive_file_id      },
    { key:"W", label:"E-Waybill",       fileId: inv.waybill_drive_file_id },
    { key:"G", label:"GRN",             fileId: inv.grn_drive_file_id     },
    { key:"M", label:"Material Return", fileId: inv.mrn_drive_file_id     },
  ];
  return (
    <span style={{ display:"inline-flex", gap:2 }}>
      {docs.map(d => {
        const active = !!d.fileId;
        return (
          <span key={d.key}
            title={active ? `${d.label}: scanned — click to open` : `${d.label}: not scanned yet`}
            onClick={e => { if (!active) return; e.stopPropagation(); window.open(`https://drive.google.com/file/d/${d.fileId}/preview`, "_blank"); }}
            style={{
              display:"inline-flex", alignItems:"center", justifyContent:"center",
              width:18, height:18, borderRadius:3, fontSize:10, fontWeight:700,
              background: active ? "#1E3A5F" : "#E5E7EB",
              color:      active ? "#fff"    : "#9CA3AF",
              cursor:     active ? "pointer" : "default",
            }}
          >{d.key}</span>
        );
      })}
    </span>
  );
}

// ── Styles ────────────────────────────────────────────────────────────────────

const s = {
  wrap:      { fontFamily:"'Inter',system-ui,sans-serif", background:"#F8FAFC", minHeight:"100vh", color:"#111318" },
  header:    { background:"#1E3A5F", color:"#fff", padding:"16px 24px", display:"flex", alignItems:"center", justifyContent:"space-between", gap:12 },
  h1:        { margin:0, fontSize:18, fontWeight:700 },
  toolbar:   { display:"flex", alignItems:"center", flexWrap:"wrap", gap:8, padding:"10px 20px", background:"#fff", borderBottom:"1px solid #E5E7EB" },
  input:     { border:"1px solid #D1D5DB", borderRadius:6, padding:"5px 10px", fontSize:13, fontFamily:"inherit", outline:"none" },
  btn:       { border:"none", borderRadius:6, padding:"6px 14px", fontSize:13, fontWeight:600, cursor:"pointer", fontFamily:"inherit" },
  primary:   { background:"#1E3A5F", color:"#fff" },
  ghost:     { background:"none", border:"1px solid #D1D5DB", color:"#374151", padding:"5px 12px" },
  rescanBar: { display:"flex", alignItems:"center", gap:10, padding:"6px 20px", background:"#EEF2FF", borderBottom:"1px solid #C7D2FE", flexWrap:"wrap" },
  table:     { width:"100%", borderCollapse:"collapse", fontSize:12 },
  th:        { padding:"7px 8px", textAlign:"left", background:"#F1F5F9", color:"#475569", fontWeight:600, fontSize:11, whiteSpace:"nowrap", borderBottom:"2px solid #E2E8F0", position:"sticky", top:0, zIndex:1 },
  td:        { padding:"7px 8px", borderBottom:"1px solid #F1F5F9", verticalAlign:"middle" },
  panel:     { position:"fixed", right:0, top:0, bottom:0, width:440, background:"#fff", boxShadow:"-4px 0 24px rgba(0,0,0,0.12)", overflowY:"auto", zIndex:200, padding:"20px 22px", fontFamily:"'Inter',system-ui,sans-serif" },
  lbl:       { fontSize:10, color:"#6B7280", fontWeight:600, margin:"8px 0 2px" },
  val:       { fontSize:13, color:"#111318", margin:0 },
  section:   { fontSize:11, fontWeight:700, color:"#1E3A5F", letterSpacing:"0.06em", textTransform:"uppercase", margin:"14px 0 6px" },
};

// ── Helpers ───────────────────────────────────────────────────────────────────

/** All Drive file IDs attached to this invoice row (invoice + all linked docs).
 *  Used for "select all files" checkbox logic so placeholders with no invoice
 *  file but a linked PO/GRN can still be queued for rescan. */
function allFileIds(inv) {
  return [
    inv.drive_file_id,
    inv.po_drive_file_id,
    inv.waybill_drive_file_id,
    inv.grn_drive_file_id,
    inv.mrn_drive_file_id,
  ].filter(Boolean);
}

/** True if any of this invoice's file IDs are in the rescan set. */
function anyInRescan(inv, rescanSet) {
  return allFileIds(inv).some(fid => rescanSet.has(fid));
}

// ── Main ──────────────────────────────────────────────────────────────────────

export default function InvoiceList() {
  const { getToken } = useAuth();
  const [data, setData]             = useState(null);
  const [loading, setLoading]       = useState(false);
  const [error, setError]           = useState(null);
  const [search, setSearch]         = useState("");
  const [statusFilter, setStatus]   = useState("");
  const [page, setPage]             = useState(1);
  const [sortBy, setSortBy]         = useState("processed_at");
  const [sortDir, setSortDir]       = useState("desc");
  const [panelInv, setPanelInv]     = useState(null);
  const [reviewInv, setReviewInv]   = useState(null);  // full detail object
  const [verifyInv, setVerifyInv]   = useState(null);  // full detail object
  const [hsnProfile, setHsnProfile] = useState(null);
  const [rescanSet, setRescanSet]   = useState(new Set());
  const [rescanning, setRescanning] = useState(false);
  const [rescanMsg, setRescanMsg]   = useState(null);

  const fetchInvoices = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const tok = await getToken();
      const p = new URLSearchParams({ page, page_size:50, sort_by:sortBy, sort_dir:sortDir });
      if (search)       p.set("search", search);
      if (statusFilter) p.set("status", statusFilter);
      const res = await fetch(`${API_BASE}/invoices?${p}`, { headers:{ Authorization:`Bearer ${tok}` } });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setData(await res.json());
    } catch (e) { setError(e.message); }
    finally { setLoading(false); }
  }, [getToken, page, search, statusFilter, sortBy, sortDir]);

  useEffect(() => { fetchInvoices(); }, [fetchInvoices]);

  useEffect(() => {
    (async () => {
      try {
        const tok = await getToken();
        const res = await fetch(`${API_BASE}/org/hsn-profile`, { headers:{ Authorization:`Bearer ${tok}` } });
        if (res.ok) setHsnProfile(await res.json());
      } catch {}
    })();
  }, [getToken]);

  // ── Rescan helpers ─────────────────────────────────────────────────────────

  function toggleFileRescan(fid) {
    if (!fid) return;
    setRescanSet(prev => { const n = new Set(prev); n.has(fid) ? n.delete(fid) : n.add(fid); return n; });
  }

  /** Toggle ALL file IDs for a given invoice row (for the row checkbox). */
  function toggleInvoiceRescan(inv) {
    const ids = allFileIds(inv);
    if (!ids.length) return;
    setRescanSet(prev => {
      const n = new Set(prev);
      const allIn = ids.every(fid => n.has(fid));
      ids.forEach(fid => allIn ? n.delete(fid) : n.add(fid));
      return n;
    });
  }

  async function rescanSelected() {
    if (rescanSet.size === 0) return;
    setRescanning(true); setRescanMsg(null);
    try {
      const tok = await getToken();
      const res = await fetch(`${API_BASE}/invoices/rescan`, {
        method: "POST",
        headers: { Authorization:`Bearer ${tok}`, "Content-Type":"application/json" },
        body: JSON.stringify({ drive_file_ids: [...rescanSet] }),
      });
      const d = await res.json();
      if (!res.ok) throw new Error(d.detail || `HTTP ${res.status}`);
      setRescanMsg(`Rescanned ${d.rescanned} file(s)`);
      setRescanSet(new Set());
      fetchInvoices();
    } catch(e) { setRescanMsg(`Rescan failed: ${e.message}`); }
    finally { setRescanning(false); }
  }

  function handleSort(col) {
    if (sortBy === col) setSortDir(d => d === "asc" ? "desc" : "asc");
    else { setSortBy(col); setSortDir("desc"); }
    setPage(1);
  }

  function parseHsn(raw) {
    if (!raw) return [];
    try { const p = typeof raw === "string" ? JSON.parse(raw) : raw; return Array.isArray(p) ? p : []; }
    catch { return []; }
  }

  // ── Side panel ──────────────────────────────────────────────────────────────
  // SidePanel is defined inside the parent so it closes over rescanSet/getToken/etc.
  // It fetches full detail async. The Review & Verify buttons wait for that fetch
  // and fall back to the sparse row object if detail never loads.

  function SidePanel({ inv, onClose }) {
    const [detail, setDetail]       = useState(null);
    const [detailLoading, setDL]    = useState(true);

    useEffect(() => {
      let cancelled = false;
      (async () => {
        try {
          const tok = await getToken();
          const res = await fetch(`${API_BASE}/invoices/${inv.invoice_id}`, { headers:{ Authorization:`Bearer ${tok}` } });
          if (res.ok && !cancelled) setDetail(await res.json());
        } catch {}
        finally { if (!cancelled) setDL(false); }
      })();
      return () => { cancelled = true; };
    }, [inv.invoice_id]);

    // Always use the best object available: detail if loaded, otherwise sparse row.
    // This means buttons work immediately (using row data) even before detail loads,
    // and get enriched data (line items etc.) once the fetch resolves.
    const rich = detail || inv;

    // All Drive file IDs attached to this invoice — for per-file rescan buttons
    const linkedFiles = [
      { label:"Invoice",        fid: inv.drive_file_id           },
      { label:"Purchase Order", fid: inv.po_drive_file_id        },
      { label:"Waybill",        fid: inv.waybill_drive_file_id   },
      { label:"GRN",            fid: inv.grn_drive_file_id       },
      { label:"MRN",            fid: inv.mrn_drive_file_id       },
    ].filter(d => d.fid);

    const hsn = parseHsn(rich.hsn_codes);

    return (
      <div style={s.panel}>
        <button
          style={{ position:"absolute",top:14,right:16,background:"none",border:"none",fontSize:20,cursor:"pointer",color:"#6B7280" }}
          onClick={onClose}
        >×</button>

        <div style={{ paddingRight:24 }}>
          <p style={s.lbl}>File</p>
          <p style={{ ...s.val, fontSize:11, wordBreak:"break-all", marginBottom:8 }}>{inv.file_name||"—"}</p>

          {inv.status === "PLACEHOLDER" && (
            <div style={{ background:"#F0FDF4",border:"1px solid #86EFAC",borderRadius:6,padding:"8px 12px",marginBottom:10,fontSize:12 }}>
              <strong>Placeholder</strong> — created from a linked PO/waybill/GRN. Sync invoices folder to fill all fields.
            </div>
          )}

          {detailLoading && (
            <p style={{ fontSize:11, color:"#9CA3AF", marginBottom:8 }}>Loading detail…</p>
          )}

          {/* Key fields grid */}
          <div style={{ display:"grid", gridTemplateColumns:"1fr 1fr", gap:"0 16px" }}>
            {[
              ["Status",       <StatusBadge status={rich.status} />],
              ["Vendor",       rich.vendor_name||"—"],
              ["GSTIN",        rich.vendor_gstin||"—"],
              ["Invoice No.",  rich.invoice_number||"—"],
              ["Invoice Date", fmtDate(rich.invoice_date)],
              ["PO Number",    rich.po_number||"—"],
              ["PO Date",      fmtDate(rich.po_date)],
              ["Delivery by",  fmtDate(rich.delivery_date_requested)],
              ["Incoterm",     rich.po_incoterm || rich.po_incoterm_raw || "—"],
              ["Waybill No.",  rich.waybill_number||"—"],
              ["GRN No.",      rich.grn_number||"—"],
              ["MRN No.",      rich.mrn_number||"—"],
              ["Total",        fmtAmount(rich.total_amount)],
              ["Taxable",      fmtAmount(rich.taxable_amount)],
              ["GST",          fmtAmount(rich.total_gst_amount)],
              ["Tax rate",     rich.tax_rate_pct != null ? `${rich.tax_rate_pct}%` : "—"],
              ["Pay by",       <PayByCell inv={rich} />],
              ["Confidence",   fmtConf(rich.confidence)],
            ].map(([lbl, val]) => (
              <div key={lbl}>
                <p style={s.lbl}>{lbl}</p>
                <p style={s.val}>{val}</p>
              </div>
            ))}
          </div>

          {/* Doc chain */}
          <p style={s.section}>Document chain</p>
          <div style={{ display:"flex", gap:8, flexWrap:"wrap", marginBottom:10 }}>
            {[
              ["PO",      rich.po_number,      rich.po_drive_file_id],
              ["Waybill", rich.waybill_number, rich.waybill_drive_file_id],
              ["GRN",     rich.grn_number,     rich.grn_drive_file_id],
              ["MRN",     rich.mrn_number,     rich.mrn_drive_file_id],
            ].map(([lbl, ref, fid]) => (
              <div key={lbl} style={{
                padding:"4px 10px", borderRadius:5, fontSize:11,
                background: fid ? "#DBEAFE" : ref ? "#FEF3C7" : "#F3F4F6",
                color:      fid ? "#1E3A5F" : ref ? "#92400E"  : "#9CA3AF",
                cursor:     fid ? "pointer" : "default",
              }}
                onClick={() => fid && window.open(`https://drive.google.com/file/d/${fid}/preview`, "_blank")}
              >
                <strong>{lbl}:</strong> {ref||"—"} {fid ? "✓" : ref ? "⚠ not scanned" : ""}
              </div>
            ))}
          </div>

          {/* HSN breakdown — lenient match shows chapter/heading warning */}
          {hsn.length > 0 && (
            <>
              <p style={s.section}>HSN codes</p>
              <div style={{ display:"flex", flexWrap:"wrap", gap:4, marginBottom:10 }}>
                {hsn.map(code => {
                  const { status, reason } = getHsnEligibility(code, hsnProfile);
                  const b = HSN_BADGE[status];
                  return (
                    <div key={code} style={{ marginBottom:4 }}>
                      <span title={reason} style={{ background:b.bg,color:b.color,borderRadius:4,padding:"1px 6px",fontSize:10,fontWeight:600,cursor:"help" }}>
                        {b.text} {code}
                      </span>
                      {(status === "chapter" || status === "review") && (
                        <div style={{ fontSize:10, color:"#C2410C", marginTop:2, maxWidth:240, lineHeight:1.4 }}>{reason}</div>
                      )}
                    </div>
                  );
                })}
              </div>
            </>
          )}

          {/* Line items (only when detail loaded) */}
          {detail?.line_items?.length > 0 && (
            <>
              <p style={s.section}>Line items</p>
              <table style={{ ...s.table, marginBottom:10 }}>
                <thead>
                  <tr>
                    {["Description","HSN","Qty","Rate","Amount"].map(h => (
                      <th key={h} style={{ ...s.th, position:"static" }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {detail.line_items.map(li => (
                    <tr key={li.line_item_id}>
                      <td style={s.td}>{li.description||"—"}</td>
                      <td style={{ ...s.td, fontFamily:"monospace" }}>{li.hsn_code||"—"}</td>
                      <td style={s.td}>{li.quantity??"—"}</td>
                      <td style={s.td}>{li.rate!=null?fmtAmount(li.rate):"—"}</td>
                      <td style={s.td}>{li.amount!=null?fmtAmount(li.amount):"—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}

          {rich.issues && (
            <div style={{ background:"#FEF3C7",borderRadius:6,padding:"8px 12px",marginBottom:12,fontSize:12,color:"#92400E" }}>
              <strong>Issues:</strong> {rich.issues}
            </div>
          )}

          {/* ── Actions ── */}
          <p style={s.section}>Actions</p>
          <div style={{ display:"flex", gap:8, flexWrap:"wrap", marginBottom:12 }}>
            {inv.drive_file_id && (
              <button
                onClick={() => window.open(`https://drive.google.com/file/d/${inv.drive_file_id}/preview`, "_blank")}
                style={{ ...s.btn, ...s.ghost }}
              >Open PDF</button>
            )}

            {/* Review & edit — always shown. Uses best available object. */}
            <button
              onClick={() => { setReviewInv(rich); onClose(); }}
              style={{ ...s.btn, ...s.primary }}
            >Review & edit</button>

            {/* Verify — always shown (not gated on confidence/status) */}
            <button
              onClick={() => { setVerifyInv(rich); onClose(); }}
              style={{ ...s.btn, background:"#059669", color:"#fff" }}
            >Verify</button>
          </div>

          {/* ── Per-file rescan queue — all linked docs, not just the invoice ── */}
          {linkedFiles.length > 0 && (
            <>
              <p style={s.section}>Queue for rescan</p>
              <div style={{ display:"flex", flexDirection:"column", gap:6 }}>
                {linkedFiles.map(({ label, fid }) => {
                  const queued = rescanSet.has(fid);
                  return (
                    <div key={fid} style={{ display:"flex", alignItems:"center", justifyContent:"space-between",
                      padding:"6px 10px", borderRadius:6, fontSize:12,
                      background: queued ? "#EEF2FF" : "#F8FAFC",
                      border: queued ? "1px solid #C7D2FE" : "1px solid #E5E7EB" }}>
                      <span style={{ color: queued ? "#3730A3" : "#374151", fontWeight: queued ? 600 : 400 }}>
                        {label}
                        {queued && <span style={{ marginLeft:6, fontSize:10, color:"#6366F1" }}>● queued</span>}
                      </span>
                      <button
                        onClick={() => toggleFileRescan(fid)}
                        style={{ ...s.btn, fontSize:11, padding:"3px 10px",
                          background: queued ? "#6366F1" : "#6B7280", color:"#fff" }}
                      >{queued ? "Remove" : "Queue"}</button>
                    </div>
                  );
                })}
              </div>
              {linkedFiles.length > 1 && (
                <button
                  onClick={() => {
                    const ids = linkedFiles.map(f => f.fid);
                    const allIn = ids.every(fid => rescanSet.has(fid));
                    setRescanSet(prev => {
                      const n = new Set(prev);
                      ids.forEach(fid => allIn ? n.delete(fid) : n.add(fid));
                      return n;
                    });
                  }}
                  style={{ ...s.btn, ...s.ghost, marginTop:6, fontSize:11, width:"100%", textAlign:"center" }}
                >
                  {linkedFiles.every(f => rescanSet.has(f.fid)) ? "Remove all from queue" : "Queue all files for this invoice"}
                </button>
              )}
            </>
          )}
        </div>
      </div>
    );
  }

  // ── Table columns ─────────────────────────────────────────────────────────

  const COLS = [
    { key:null,           label:"",         w:32  },
    { key:"vendor_name",  label:"Vendor",   sort:true  },
    { key:"invoice_date", label:"Inv Date", sort:true  },
    { key:"po_date",      label:"PO Date",  sort:false },
    { key:"po_number",    label:"PO No.",   sort:false },
    { key:"waybill_no",   label:"Waybill",  sort:false },
    { key:"grn_no",       label:"GRN",      sort:false },
    { key:"mrn_no",       label:"MRN",      sort:false },
    { key:"total_amount", label:"Amount",   sort:true  },
    { key:"pay_by",       label:"Pay by",   sort:false },
    { key:"incoterm",     label:"Incoterm", sort:false },
    { key:"docs",         label:"PWGM",     sort:false },
    { key:"status",       label:"Status",   sort:true  },
    { key:"confidence",   label:"Conf.",    sort:true  },
  ];

  const invoices   = data?.invoices   ?? [];
  const totalPages = data?.total_pages ?? 1;

  return (
    <div style={s.wrap}>

      <div style={s.header}>
        <h1 style={s.h1}>Invoices</h1>
        <button onClick={fetchInvoices} style={{ ...s.btn, background:"rgba(255,255,255,0.15)", color:"#fff" }}>↻ Refresh</button>
      </div>

      <div style={s.toolbar}>
        <input
          style={{ ...s.input, width:200 }}
          placeholder="Search vendor / invoice / PO…"
          value={search}
          onChange={e => { setSearch(e.target.value); setPage(1); }}
        />
        <select style={s.input} value={statusFilter} onChange={e => { setStatus(e.target.value); setPage(1); }}>
          <option value="">All statuses</option>
          <option value="PASSED">Passed</option>
          <option value="WARNING">Warning</option>
          <option value="FAILED">Failed</option>
          <option value="NEEDS_MANUAL_REVIEW">Needs review</option>
          <option value="PLACEHOLDER">Placeholder</option>
        </select>
        <button style={{ ...s.btn, ...s.primary }} onClick={() => { setPage(1); fetchInvoices(); }}>Search</button>
      </div>

      {/* Rescan bar — appears when anything is queued */}
      {rescanSet.size > 0 && (
        <div style={s.rescanBar}>
          <span style={{ fontSize:12, color:"#3730A3", fontWeight:600 }}>
            {rescanSet.size} file{rescanSet.size > 1 ? "s" : ""} queued for rescan
          </span>
          <button onClick={rescanSelected} disabled={rescanning}
            style={{ ...s.btn, ...s.primary, background:"#312E81" }}>
            {rescanning ? "Rescanning…" : "↻ Rescan now"}
          </button>
          <button onClick={() => setRescanSet(new Set())} style={{ ...s.btn, ...s.ghost }}>Clear all</button>
          {rescanMsg && <span style={{ fontSize:12, color:"#15803D" }}>{rescanMsg}</span>}
        </div>
      )}

      {loading && <p style={{ padding:"20px 24px", color:"#6B7280" }}>Loading…</p>}
      {error   && <p style={{ padding:"20px 24px", color:"#DC2626" }}>Error: {error}</p>}
      {!loading && !error && invoices.length === 0 && (
        <p style={{ padding:"20px 24px", color:"#6B7280" }}>No invoices found.</p>
      )}

      {!loading && invoices.length > 0 && (
        <div style={{ overflowX:"auto" }}>
          <table style={s.table}>
            <thead>
              <tr>
                {COLS.map(col => (
                  <th
                    key={col.label}
                    style={{ ...s.th, width:col.w||undefined, cursor:col.sort?"pointer":"default" }}
                    onClick={() => col.sort && col.key && handleSort(col.key)}
                  >
                    {col.label}
                    {col.sort && col.key && (
                      sortBy === col.key
                        ? (sortDir === "asc" ? " ↑" : " ↓")
                        : <span style={{ opacity:0.3 }}> ↕</span>
                    )}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {invoices.map(inv => {
                const isPlaceholder = inv.status === "PLACEHOLDER";
                const inRescan      = anyInRescan(inv, rescanSet);
                const hasAnyFile    = allFileIds(inv).length > 0;
                return (
                  <tr
                    key={inv.invoice_id}
                    style={{ cursor:"pointer", background: inRescan ? "#EEF2FF" : isPlaceholder ? "#FAFFF7" : "" }}
                    onMouseEnter={e => { if (!inRescan && !isPlaceholder) e.currentTarget.style.background = "#F8FAFC"; }}
                    onMouseLeave={e => { e.currentTarget.style.background = inRescan ? "#EEF2FF" : isPlaceholder ? "#FAFFF7" : ""; }}
                    onClick={() => setPanelInv(inv)}
                  >
                    {/* Checkbox — toggles ALL file IDs for this row */}
                    <td
                      style={{ ...s.td, width:32, paddingRight:0 }}
                      onClick={e => { e.stopPropagation(); toggleInvoiceRescan(inv); }}
                    >
                      {hasAnyFile && (
                        <input
                          type="checkbox"
                          checked={inRescan}
                          onChange={() => {}}
                          style={{ cursor:"pointer" }}
                        />
                      )}
                    </td>

                    {/* Vendor */}
                    <td style={s.td}>
                      <div style={{ fontWeight:600, fontSize:12 }}>
                        {inv.vendor_name || (isPlaceholder ? <em style={{ color:"#9CA3AF" }}>Placeholder</em> : "—")}
                      </div>
                      {inv.vendor_gstin && <div style={{ fontSize:10, color:"#6B7280" }}>{inv.vendor_gstin}</div>}
                    </td>

                    {/* Invoice Date */}
                    <td style={{ ...s.td, fontSize:11, color:inv.invoice_date?"#374151":"#9CA3AF", whiteSpace:"nowrap" }}>
                      {fmtDate(inv.invoice_date)}
                    </td>

                    {/* PO Date */}
                    <td style={{ ...s.td, fontSize:11, color:inv.po_date?"#374151":"#9CA3AF", whiteSpace:"nowrap" }}>
                      {fmtDate(inv.po_date)}
                    </td>

                    {/* PO No. */}
                    <td style={{ ...s.td, fontFamily:"monospace", fontSize:11, color:inv.po_number?"#111318":"#9CA3AF" }}>
                      {inv.po_number||"—"}
                    </td>

                    {/* Waybill No. */}
                    <td style={{ ...s.td, fontFamily:"monospace", fontSize:11, color:inv.waybill_number?"#111318":"#9CA3AF" }}>
                      {inv.waybill_number||"—"}
                    </td>

                    {/* GRN No. */}
                    <td style={{ ...s.td, fontFamily:"monospace", fontSize:11, color:inv.grn_number?"#111318":"#9CA3AF" }}>
                      {inv.grn_number||"—"}
                    </td>

                    {/* MRN No. */}
                    <td style={{ ...s.td, fontFamily:"monospace", fontSize:11, color:inv.mrn_number?"#111318":"#9CA3AF" }}>
                      {inv.mrn_number||"—"}
                    </td>

                    {/* Amount */}
                    <td style={{ ...s.td, textAlign:"right", whiteSpace:"nowrap", fontWeight:600, color:inv.total_amount?"#111318":"#9CA3AF" }}>
                      {fmtAmount(inv.total_amount)}
                    </td>

                    {/* Pay by */}
                    <td style={{ ...s.td, whiteSpace:"nowrap" }}>
                      <PayByCell inv={inv} />
                    </td>

                    {/* Incoterm */}
                    <td style={{ ...s.td, fontSize:11, color:inv.po_incoterm||inv.po_incoterm_raw?"#374151":"#9CA3AF" }}>
                      {inv.po_incoterm || inv.po_incoterm_raw || "—"}
                    </td>

                    {/* PWGM */}
                    <td style={{ ...s.td, whiteSpace:"nowrap" }} onClick={e => e.stopPropagation()}>
                      <DocChainBadge inv={inv} />
                    </td>

                    {/* Status */}
                    <td style={s.td}><StatusBadge status={inv.status} /></td>

                    {/* Confidence */}
                    <td style={{ ...s.td, color:"#6B7280", textAlign:"right" }}>
                      {fmtConf(inv.confidence)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* Pagination */}
      {!loading && totalPages > 1 && (
        <div style={{ display:"flex", gap:8, padding:"12px 20px", alignItems:"center", fontSize:13 }}>
          <button style={{ ...s.btn, ...s.ghost }} disabled={page <= 1} onClick={() => setPage(p => p-1)}>← Prev</button>
          <span style={{ color:"#6B7280" }}>
            Page {page} of {totalPages}{data?.total_count != null && ` · ${data.total_count} total`}
          </span>
          <button style={{ ...s.btn, ...s.ghost }} disabled={page >= totalPages} onClick={() => setPage(p => p+1)}>Next →</button>
        </div>
      )}

      {/* Side panel */}
      {panelInv && <SidePanel inv={panelInv} onClose={() => setPanelInv(null)} />}

      {/* Modals — correct props: invoiceId + data + getToken */}
      {reviewInv && (
        <ReviewModal
          invoiceId={reviewInv.invoice_id}
          data={reviewInv}
          getToken={getToken}
          onClose={() => { setReviewInv(null); fetchInvoices(); }}
          onSaved={() => { setReviewInv(null); fetchInvoices(); }}
        />
      )}
      {verifyInv && (
        <VerifyModal
          invoiceId={verifyInv.invoice_id}
          data={verifyInv}
          getToken={getToken}
          onClose={() => { setVerifyInv(null); fetchInvoices(); }}
          onVerified={() => { setVerifyInv(null); fetchInvoices(); }}
        />
      )}
    </div>
  );
}