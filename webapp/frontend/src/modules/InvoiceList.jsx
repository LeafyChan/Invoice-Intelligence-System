import { useState, useEffect, useCallback, useRef } from "react";
import { useAuth } from "@clerk/clerk-react";
import ReviewModal from "../components/ReviewModal";
import VerifyModal from "../components/VerifyModal";
import AdvancedSearch from "./AdvancedSearch";

const API_BASE = import.meta.env.VITE_API_BASE || "";

function fmtAmount(v) {
  if (v == null) return "—";
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: 0,
  }).format(v);
}
function fmtDate(v) {
  if (!v) return "—";
  try {
    return new Date(v).toLocaleDateString("en-IN", {
      day: "2-digit",
      month: "short",
      year: "numeric",
    });
  } catch {
    return v;
  }
}
function fmtConf(v) {
  if (v == null) return "—";
  const pct = v > 1 ? v : v * 100;
  return `${Math.round(pct)}%`;
}

function parseDueDateFromTerms(inv) {
  const terms = (inv.payment_terms || inv.po_payment_terms || "").trim();
  const invoiceDate = inv.invoice_date ? new Date(inv.invoice_date) : null;
  const grnDate = inv.grn_date ? new Date(inv.grn_date) : null;
  if (!terms) return null;
  const lower = terms.toLowerCase();
  if (
    /\b(cod|cash on delivery|immediate|due on delivery|on delivery)\b/.test(
      lower,
    )
  )
    return { date: null, type: "on_delivery", label: "On delivery" };
  const grnMatch = lower.match(
    /(\d+)\s*days?\s*(?:from|after)\s*(?:grn|receipt|delivery)/,
  );
  if (grnMatch) {
    const base = grnDate || invoiceDate;
    if (base) {
      const d = new Date(base);
      d.setDate(d.getDate() + parseInt(grnMatch[1], 10));
      return { date: d, type: "from_grn" };
    }
  }
  const netMatch = lower.match(/(?:net\s*|within\s+)?(\d+)\s*days?/);
  if (netMatch && invoiceDate) {
    const d = new Date(invoiceDate);
    d.setDate(d.getDate() + parseInt(netMatch[1], 10));
    return { date: d, type: "net_days" };
  }
  return null;
}

function computeEffectiveDueDate(inv) {
  if (inv.effective_due_date)
    return { date: new Date(inv.effective_due_date), source: "column" };
  const fromTerms = parseDueDateFromTerms(inv);
  if (fromTerms) return { ...fromTerms, source: "terms" };
  return null;
}

function resolveIsOverdue(inv) {
  if (inv.is_overdue === true) return true;
  if (inv.is_overdue === false && inv.effective_due_date) return false;
  if (inv.is_paid) return false;
  const eff = computeEffectiveDueDate(inv);
  if (!eff || !eff.date || eff.type === "on_delivery") return false;
  return eff.date < new Date();
}

function PayByCell({ inv, onMarkPaid, markingPaid }) {
  const eff = computeEffectiveDueDate(inv);
  const overdue = resolveIsOverdue(inv);
  if (inv.is_paid)
    return (
      <span
        style={{
          background: "#ECFDF5",
          color: "#059669",
          border: "1px solid rgba(5, 150, 105, 0.2)",
          borderRadius: 6,
          padding: "2px 8px",
          fontSize: 11,
          fontWeight: 600,
        }}
      >
        ✓ Paid
      </span>
    );
  if (!eff) return <span style={{ color: "#94A3B8" }}>—</span>;
  if (eff.type === "on_delivery")
    return (
      <span
        style={{
          background: "#EFF6FF",
          color: "#2563EB",
          border: "1px solid rgba(37, 99, 235, 0.2)",
          borderRadius: 6,
          padding: "2px 8px",
          fontSize: 11,
          fontWeight: 600,
        }}
      >
        On delivery
      </span>
    );
  if (!eff.date)
    return <span style={{ color: "#94A3B8", fontSize: 11 }}>—</span>;
  const today = new Date();
  const diff = Math.ceil((eff.date - today) / 86400000);
  if (overdue) {
    return (
      <span
        style={{
          display: "inline-flex",
          alignItems: "center",
          gap: 6,
          flexWrap: "wrap",
        }}
      >
        <span
          style={{
            background: "#FFF1F2",
            color: "#E11D48",
            border: "1px solid rgba(225, 29, 72, 0.2)",
            borderRadius: 6,
            padding: "2px 8px",
            fontSize: 11,
            fontWeight: 700,
          }}
        >
          Overdue · {fmtDate(eff.date.toISOString())}
        </span>
        {onMarkPaid && (
          <button
            disabled={markingPaid}
            onClick={(e) => {
              e.stopPropagation();
              onMarkPaid();
            }}
            style={{
              background: markingPaid ? "#E2E8F0" : "#059669",
              color: markingPaid ? "#94A3B8" : "#fff",
              border: "none",
              borderRadius: 6,
              padding: "3px 8px",
              fontSize: 10,
              fontWeight: 600,
              cursor: markingPaid ? "default" : "pointer",
              fontFamily: "inherit",
            }}
          >
            {markingPaid ? "Saving…" : "Mark paid"}
          </button>
        )}
      </span>
    );
  }
  const color = diff <= 7 ? "#D97706" : "#475569";
  const bg = diff <= 7 ? "#FFFBEB" : "transparent";
  return (
    <span
      style={{
        fontSize: 11,
        color,
        background: bg,
        borderRadius: 6,
        padding: bg !== "transparent" ? "2px 6px" : 0,
        fontWeight: diff <= 7 ? 600 : 400,
      }}
    >
      {fmtDate(eff.date.toISOString())}
    </span>
  );
}

function OverdueBanner({ count, onFilter }) {
  if (count === 0) return null;
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        padding: "12px 24px",
        background: "#FFF1F2",
        borderBottom: "1px solid #FECDD3",
      }}
    >
      <span style={{ fontSize: 13, color: "#9F1239", fontWeight: 600 }}>
        ⚠️ {count} invoice{count > 1 ? "s" : ""} past payment due date
      </span>
      <button
        onClick={onFilter}
        style={{
          border: "1px solid #FDA4AF",
          background: "#fff",
          color: "#E11D48",
          borderRadius: 6,
          padding: "5px 12px",
          fontSize: 12,
          fontWeight: 600,
          cursor: "pointer",
          fontFamily: "inherit",
          boxShadow: "0 1px 2px 0 rgba(0,0,0,0.05)",
        }}
      >
        Show overdue only
      </button>
    </div>
  );
}

function getHsnEligibility(code, profile) {
  if (!code || !profile)
    return { status: "unknown", reason: "No HSN profile loaded" };
  const c = String(code).trim();
  if (profile.expected_hsn_codes?.some((p) => p.code === c))
    return {
      status: "eligible",
      reason: "Exact match — expected business purchase",
    };
  if (profile.ambiguous_hsn_codes?.some((p) => p.code === c))
    return {
      status: "review",
      reason: "Ambiguous — verify before claiming ITC",
    };
  const excluded = [
    ...(profile.expected_hsn_codes || []),
    ...(profile.ambiguous_hsn_codes || []),
  ].filter((p) => p.confidence === "excluded");
  if (excluded.some((p) => p.code === c))
    return {
      status: "excluded",
      reason: "Blacklisted — will not be counted in ITC",
    };
  if (c.length >= 4) {
    const pfx4 = c.slice(0, 4);
    if (
      profile.expected_hsn_codes?.some((p) => p.code.startsWith(pfx4)) ||
      profile.ambiguous_hsn_codes?.some((p) => p.code.startsWith(pfx4))
    )
      return {
        status: "chapter",
        reason: `4-digit heading ${pfx4} matches but exact code ${c} not listed.`,
      };
  }
  const ch = c.slice(0, 2);
  if (
    profile.expected_hsn_codes?.some((p) => p.code.startsWith(ch)) ||
    profile.ambiguous_hsn_codes?.some((p) => p.code.startsWith(ch))
  )
    return {
      status: "chapter",
      reason: `Chapter ${ch} matches but exact code ${c} not listed.`,
    };
  return {
    status: "unknown",
    reason: `Code ${c} not in HSN profile — ITC likely ineligible`,
  };
}

const HSN_BADGE = {
  eligible: { bg: "#ECFDF5", color: "#059669", text: "✓" },
  review: { bg: "#FEF3C7", color: "#B45309", text: "?" },
  chapter: { bg: "#FFF7ED", color: "#C2410C", text: "⚠️" },
  unknown: { bg: "#F1F5F9", color: "#64748B", text: "—" },
  excluded: { bg: "#FFF1F2", color: "#E11D48", text: "✗" },
};

function HsnCodeBadge({ code, hsnProfile, getToken, onProfileUpdate }) {
  const [open, setOpen] = useState(false);
  const [status, setStatus] = useState(null);
  const ref = useRef(null);
  useEffect(() => {
    if (!open) return;
    function handleClick(e) {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false);
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [open]);
  const { status: eligStatus, reason } = getHsnEligibility(code, hsnProfile);
  const b = HSN_BADGE[eligStatus] || HSN_BADGE.unknown;
  async function act(confidence) {
    setStatus(confidence === "expected" ? "adding" : "blacklisting");
    try {
      const tok = await getToken({ skipCache: true });
      const res = await fetch(`${API_BASE}/org/hsn-profile/codes`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${tok}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          code: code.trim().toUpperCase(),
          code_type: "HSN",
          confidence,
        }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setStatus(confidence === "expected" ? "done_add" : "done_bl");
      onProfileUpdate?.();
      setTimeout(() => setOpen(false), 1200);
    } catch {
      setStatus("error");
    }
  }
  return (
    <div
      style={{
        position: "relative",
        display: "inline-block",
        marginRight: 4,
        marginBottom: 4,
      }}
      ref={ref}
    >
      <span
        title={reason}
        onClick={() => setOpen((o) => !o)}
        style={{
          background: b.bg,
          color: b.color,
          borderRadius: 6,
          padding: "3px 8px",
          fontSize: 11,
          fontWeight: 600,
          cursor: "pointer",
          border: open ? `1px solid ${b.color}` : "1px solid transparent",
          userSelect: "none",
        }}
      >
        {b.text} {code}
      </span>
      {open && (
        <div
          style={{
            position: "absolute",
            top: "calc(100% + 4px)",
            left: 0,
            zIndex: 500,
            background: "#fff",
            border: "1px solid #E2E8F0",
            borderRadius: 8,
            boxShadow: "0 10px 25px -5px rgba(0,0,0,0.1)",
            padding: "12px 14px",
            minWidth: 220,
            fontFamily: "'Inter',system-ui,sans-serif",
          }}
        >
          <div
            style={{
              fontSize: 11,
              color: "#64748B",
              marginBottom: 10,
              lineHeight: 1.4,
            }}
          >
            {reason}
          </div>
          {status === "done_add" && (
            <div style={{ fontSize: 12, color: "#059669", fontWeight: 600 }}>
              ✓ Added to ITC profile
            </div>
          )}
          {status === "done_bl" && (
            <div style={{ fontSize: 12, color: "#E11D48", fontWeight: 600 }}>
              ✗ Blacklisted
            </div>
          )}
          {status === "error" && (
            <div style={{ fontSize: 12, color: "#E11D48" }}>
              Error — try again
            </div>
          )}
          {(!status || status === "error") && (
            <div style={{ display: "flex", gap: 6 }}>
              <button
                onClick={() => act("expected")}
                style={{
                  flex: 1,
                  background: "#ECFDF5",
                  color: "#059669",
                  border: "1px solid #A7F3D0",
                  borderRadius: 6,
                  padding: "6px 8px",
                  fontSize: 11,
                  fontWeight: 600,
                  cursor: "pointer",
                  fontFamily: "inherit",
                }}
              >
                ✓ Add
              </button>
              <button
                onClick={() => act("excluded")}
                style={{
                  flex: 1,
                  background: "#FFF1F2",
                  color: "#E11D48",
                  border: "1px solid #FECDD3",
                  borderRadius: 6,
                  padding: "6px 8px",
                  fontSize: 11,
                  fontWeight: 600,
                  cursor: "pointer",
                  fontFamily: "inherit",
                }}
              >
                ✗ Blacklist
              </button>
            </div>
          )}
          {(status === "adding" || status === "blacklisting") && (
            <div style={{ fontSize: 12, color: "#64748B" }}>
              {status === "adding" ? "Adding…" : "Blacklisting…"}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

const STATUS_STYLES = {
  PASSED: { label: "Passed", bg: "#ECFDF5", color: "#059669" },
  WARNING: { label: "Warning", bg: "#FEF3C7", color: "#B45309" },
  FAILED: { label: "Failed", bg: "#FFF1F2", color: "#E11D48" },
  NEEDS_MANUAL_REVIEW: {
    label: "Needs review",
    bg: "#EEF2FF",
    color: "#4F46E5",
  },
  PLACEHOLDER: { label: "Placeholder", bg: "#F0FDF4", color: "#15803D" },
};

function StatusBadge({ status }) {
  const st = STATUS_STYLES[status] || {
    label: status || "Unknown",
    bg: "#F1F5F9",
    color: "#475569",
  };
  return (
    <span
      style={{
        background: st.bg,
        color: st.color,
        border: `1px solid ${st.color}20`,
        borderRadius: 6,
        padding: "3px 8px",
        fontSize: 11,
        fontWeight: 600,
        whiteSpace: "nowrap",
      }}
    >
      {st.label}
    </span>
  );
}

function DocChainBadge({ inv }) {
  const docs = [
    { key: "P", label: "Purchase Order", fileId: inv.po_drive_file_id },
    { key: "W", label: "E-Waybill", fileId: inv.waybill_drive_file_id },
    { key: "G", label: "GRN", fileId: inv.grn_drive_file_id },
    { key: "M", label: "Material Return", fileId: inv.mrn_drive_file_id },
  ];
  return (
    <span style={{ display: "inline-flex", gap: 3 }}>
      {docs.map((d) => {
        const active = !!d.fileId;
        return (
          <span
            key={d.key}
            title={active ? `${d.label}: scanned` : `${d.label}: not scanned`}
            onClick={(e) => {
              if (!active) return;
              e.stopPropagation();
              window.open(
                `https://drive.google.com/file/d/${d.fileId}/preview`,
                "_blank",
              );
            }}
            style={{
              display: "inline-flex",
              alignItems: "center",
              justifyContent: "center",
              width: 20,
              height: 20,
              borderRadius: 4,
              fontSize: 10,
              fontWeight: 700,
              background: active ? "#0F172A" : "#F1F5F9",
              color: active ? "#fff" : "#94A3B8",
              cursor: active ? "pointer" : "default",
            }}
          >
            {d.key}
          </span>
        );
      })}
    </span>
  );
}

const s = {
  wrap: {
    fontFamily: "'Inter',system-ui,sans-serif",
    background: "#F8FAFC",
    minHeight: "100vh",
    color: "#0F172A",
  },
  header: {
    background: "#FFFFFF",
    borderBottom: "1px solid #E2E8F0",
    padding: "20px 24px",
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 12,
  },
  h1: { margin: 0, fontSize: 20, fontWeight: 700, color: "#0F172A" },
  btn: {
    border: "none",
    borderRadius: 6,
    padding: "7px 14px",
    fontSize: 13,
    fontWeight: 600,
    cursor: "pointer",
    fontFamily: "inherit",
  },
  primary: { background: "#4F46E5", color: "#fff" },
  ghost: {
    background: "#FFFFFF",
    border: "1px solid #CBD5E1",
    color: "#334155",
    padding: "6px 12px",
  },
  rescanBar: {
    display: "flex",
    alignItems: "center",
    gap: 12,
    padding: "10px 24px",
    background: "#EEF2FF",
    borderBottom: "1px solid #C7D2FE",
    flexWrap: "wrap",
  },
  table: { width: "100%", borderCollapse: "collapse", fontSize: 13 },
  th: {
    padding: "10px 12px",
    textAlign: "left",
    background: "#F8FAFC",
    color: "#475569",
    fontWeight: 600,
    fontSize: 11,
    textTransform: "uppercase",
    letterSpacing: "0.05em",
    whiteSpace: "nowrap",
    borderBottom: "1px solid #E2E8F0",
    position: "sticky",
    top: 0,
    zIndex: 1,
  },
  td: {
    padding: "12px",
    borderBottom: "1px solid #F1F5F9",
    verticalAlign: "middle",
  },
  panel: {
    position: "fixed",
    right: 0,
    top: 0,
    bottom: 0,
    width: 460,
    background: "#fff",
    boxShadow: "-10px 0 25px -5px rgba(0,0,0,0.1)",
    overflowY: "auto",
    zIndex: 200,
    padding: "24px",
    fontFamily: "'Inter',system-ui,sans-serif",
    borderLeft: "1px solid #E2E8F0",
  },
  lbl: {
    fontSize: 11,
    color: "#64748B",
    fontWeight: 600,
    margin: "10px 0 2px",
    textTransform: "uppercase",
    letterSpacing: "0.03em",
  },
  val: { fontSize: 13, color: "#0F172A", margin: 0, fontWeight: 500 },
  section: {
    fontSize: 11,
    fontWeight: 700,
    color: "#4F46E5",
    letterSpacing: "0.06em",
    textTransform: "uppercase",
    margin: "16px 0 8px",
  },
};

function allFileIds(inv) {
  return [
    inv.drive_file_id,
    inv.po_drive_file_id,
    inv.waybill_drive_file_id,
    inv.grn_drive_file_id,
    inv.mrn_drive_file_id,
  ].filter(Boolean);
}
function anyInRescan(inv, rescanSet) {
  return allFileIds(inv).some((fid) => rescanSet.has(fid));
}

function SidePanel({
  inv,
  onClose,
  getToken,
  hsnProfile,
  onHsnProfileUpdate,
  rescanSet,
  setRescanSet,
  setReviewInv,
  setVerifyInv,
  onMarkPaid,
}) {
  const [detail, setDetail] = useState(null);
  const [detailLoading, setDL] = useState(true);
  const [markingPaid, setMarkingPaid] = useState(false);
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const tok = await getToken({ skipCache: true });
        const res = await fetch(`${API_BASE}/invoices/${inv.invoice_id}`, {
          headers: { Authorization: `Bearer ${tok}` },
        });
        if (res.ok && !cancelled) setDetail(await res.json());
      } catch {
      } finally {
        if (!cancelled) setDL(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [inv.invoice_id, getToken]);
  const rich = detail ? { ...inv, ...detail } : inv;
  const linkedFiles = [
    { label: "Invoice", fid: inv.drive_file_id },
    { label: "Purchase Order", fid: inv.po_drive_file_id },
    { label: "Waybill", fid: inv.waybill_drive_file_id },
    { label: "GRN", fid: inv.grn_drive_file_id },
    { label: "MRN", fid: inv.mrn_drive_file_id },
  ].filter((d) => d.fid);
  function toggleFileRescan(fid) {
    if (!fid) return;
    setRescanSet((prev) => {
      const n = new Set(prev);
      n.has(fid) ? n.delete(fid) : n.add(fid);
      return n;
    });
  }
  const hsn = (() => {
    const raw = rich.hsn_codes;
    if (!raw) return [];
    try {
      const p = typeof raw === "string" ? JSON.parse(raw) : raw;
      return Array.isArray(p) ? p : [];
    } catch {
      return [];
    }
  })();
  async function handleMarkPaid() {
    setMarkingPaid(true);
    await onMarkPaid(inv.invoice_id);
    setMarkingPaid(false);
    onClose();
  }
  const overdue = resolveIsOverdue(inv);
  return (
    <div style={s.panel}>
      <button
        style={{
          position: "absolute",
          top: 20,
          right: 20,
          background: "#F1F5F9",
          border: "none",
          borderRadius: 6,
          width: 28,
          height: 28,
          fontSize: 16,
          cursor: "pointer",
          color: "#475569",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
        }}
        onClick={onClose}
      >
        ×
      </button>
      <div style={{ paddingRight: 24 }}>
        <p style={s.lbl}>File Source</p>
        <p
          style={{
            ...s.val,
            fontSize: 12,
            wordBreak: "break-all",
            marginBottom: 12,
            color: "#475569",
          }}
        >
          {inv.file_name || "—"}
        </p>
        {overdue && !inv.is_paid && (
          <div
            style={{
              background: "#FFF1F2",
              border: "1px solid #FECDD3",
              borderRadius: 8,
              padding: "10px 14px",
              marginBottom: 14,
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              gap: 8,
            }}
          >
            <span style={{ fontSize: 12, color: "#9F1239", fontWeight: 600 }}>
              ⚠️ Payment overdue
            </span>
            <button
              disabled={markingPaid}
              onClick={handleMarkPaid}
              style={{
                background: "#059669",
                color: "#fff",
                border: "none",
                borderRadius: 6,
                padding: "5px 12px",
                fontSize: 12,
                fontWeight: 600,
                cursor: markingPaid ? "default" : "pointer",
                fontFamily: "inherit",
              }}
            >
              {markingPaid ? "Saving…" : "Mark as paid"}
            </button>
          </div>
        )}
        {inv.is_paid && (
          <div
            style={{
              background: "#ECFDF5",
              border: "1px solid #A7F3D0",
              borderRadius: 8,
              padding: "10px 14px",
              marginBottom: 14,
              fontSize: 12,
              color: "#065F46",
              fontWeight: 600,
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
            }}
          >
            <span>
              ✓ Paid{rich.paid_at ? ` on ${fmtDate(rich.paid_at)}` : ""}
            </span>
            <button
              onClick={async () => {
                const tok = await getToken({ skipCache: true });
                await fetch(
                  `${API_BASE}/invoices/${inv.invoice_id}/unmark-paid`,
                  {
                    method: "PATCH",
                    headers: { Authorization: `Bearer ${tok}` },
                  },
                );
                onClose();
              }}
              style={{
                background: "none",
                border: "1px solid #A7F3D0",
                borderRadius: 4,
                padding: "2px 8px",
                fontSize: 11,
                color: "#065F46",
                cursor: "pointer",
                fontFamily: "inherit",
              }}
            >
              Undo
            </button>
          </div>
        )}
        {inv.status === "PLACEHOLDER" && (
          <div
            style={{
              background: "#F0FDF4",
              border: "1px solid #86EFAC",
              borderRadius: 8,
              padding: "10px 14px",
              marginBottom: 14,
              fontSize: 12,
              color: "#166534",
            }}
          >
            <strong>Placeholder</strong> — created from linked documents.
          </div>
        )}
        {detailLoading && (
          <p style={{ fontSize: 12, color: "#94A3B8", marginBottom: 12 }}>
            Loading complete record…
          </p>
        )}
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "1fr 1fr",
            gap: "4px 16px",
          }}
        >
          {[
            ["Status", <StatusBadge status={rich.status} />],
            ["Vendor", rich.vendor_name || "—"],
            ["GSTIN", rich.vendor_gstin || "—"],
            ["Invoice No.", rich.invoice_number || "—"],
            ["Invoice Date", fmtDate(rich.invoice_date)],
            ["PO Number", rich.po_number || "—"],
            ["PO Date", fmtDate(rich.po_date)],
            ["Delivery by", fmtDate(rich.delivery_date_requested)],
            ["Incoterm", rich.po_incoterm || rich.po_incoterm_raw || "—"],
            ["Waybill No.", rich.waybill_number || "—"],
            ["GRN No.", rich.grn_number || "—"],
            ["MRN No.", rich.mrn_number || "—"],
            ["Total", fmtAmount(rich.total_amount)],
            ["Taxable", fmtAmount(rich.taxable_amount)],
            ["GST", fmtAmount(rich.total_gst_amount)],
            [
              "Tax rate",
              rich.tax_rate_pct != null ? `${rich.tax_rate_pct}%` : "—",
            ],
            ["Pay by", <PayByCell inv={rich} />],
            ["Confidence", fmtConf(rich.confidence)],
          ].map(([lbl, val]) => (
            <div key={lbl} style={{ marginBottom: 8 }}>
              <p style={s.lbl}>{lbl}</p>
              <p style={s.val}>{val}</p>
            </div>
          ))}
        </div>

        <p style={s.section}>Document Chain</p>
        <div
          style={{
            display: "flex",
            gap: 6,
            flexWrap: "wrap",
            marginBottom: 14,
          }}
        >
          {[
            ["PO", rich.po_number, rich.po_drive_file_id],
            ["Waybill", rich.waybill_number, rich.waybill_drive_file_id],
            ["GRN", rich.grn_number, rich.grn_drive_file_id],
            ["MRN", rich.mrn_number, rich.mrn_drive_file_id],
          ].map(([lbl, ref, fid]) => (
            <div
              key={lbl}
              style={{
                padding: "6px 10px",
                borderRadius: 6,
                fontSize: 11,
                background: fid ? "#EEF2FF" : ref ? "#FEF3C7" : "#F1F5F9",
                color: fid ? "#4F46E5" : ref ? "#B45309" : "#94A3B8",
                border: `1px solid ${fid ? "#C7D2FE" : ref ? "#FDE68A" : "#E2E8F0"}`,
                cursor: fid ? "pointer" : "default",
                fontWeight: 500,
              }}
              onClick={() =>
                fid &&
                window.open(
                  `https://drive.google.com/file/d/${fid}/preview`,
                  "_blank",
                )
              }
            >
              <strong>{lbl}:</strong> {ref || "—"}{" "}
              {fid ? "✓" : ref ? "⚠️ missing" : ""}
            </div>
          ))}
        </div>

        {hsn.length > 0 && (
          <>
            <p style={s.section}>
              HSN Codes{" "}
              <span
                style={{
                  fontSize: 10,
                  fontWeight: 400,
                  color: "#94A3B8",
                  textTransform: "none",
                  letterSpacing: 0,
                }}
              >
                (click to manage)
              </span>
            </p>
            <div
              style={{
                display: "flex",
                flexWrap: "wrap",
                gap: 4,
                marginBottom: 14,
              }}
            >
              {hsn.map((code) => (
                <HsnCodeBadge
                  key={code}
                  code={code}
                  hsnProfile={hsnProfile}
                  getToken={getToken}
                  onProfileUpdate={onHsnProfileUpdate}
                />
              ))}
            </div>
          </>
        )}

        {detail?.line_items?.length > 0 && (
          <>
            <p style={s.section}>Line Items</p>
            <div
              style={{
                border: "1px solid #E2E8F0",
                borderRadius: 8,
                overflow: "hidden",
                marginBottom: 14,
              }}
            >
              <table style={{ ...s.table, marginBottom: 0 }}>
                <thead>
                  <tr>
                    {["Description", "HSN", "Qty", "Rate", "Amount"].map(
                      (h) => (
                        <th
                          key={h}
                          style={{
                            ...s.th,
                            position: "static",
                            background: "#F8FAFC",
                          }}
                        >
                          {h}
                        </th>
                      ),
                    )}
                  </tr>
                </thead>
                <tbody>
                  {detail.line_items.map((li) => (
                    <tr key={li.line_item_id}>
                      <td style={s.td}>{li.description || "—"}</td>
                      <td style={s.td}>
                        {li.hsn_code ? (
                          <HsnCodeBadge
                            code={li.hsn_code}
                            hsnProfile={hsnProfile}
                            getToken={getToken}
                            onProfileUpdate={onHsnProfileUpdate}
                          />
                        ) : (
                          "—"
                        )}
                      </td>
                      <td style={s.td}>{li.quantity ?? "—"}</td>
                      <td style={s.td}>
                        {li.rate != null ? fmtAmount(li.rate) : "—"}
                      </td>
                      <td style={s.td}>
                        {li.amount != null ? fmtAmount(li.amount) : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}

        {rich.issues && (
          <div
            style={{
              background: "#FFFBEB",
              border: "1px solid #FDE68A",
              borderRadius: 8,
              padding: "10px 14px",
              marginBottom: 14,
              fontSize: 12,
              color: "#B45309",
            }}
          >
            <strong>Issues Identified:</strong> {rich.issues}
          </div>
        )}

        <p style={s.section}>Actions</p>
        <div
          style={{
            display: "flex",
            gap: 8,
            flexWrap: "wrap",
            marginBottom: 16,
          }}
        >
          {inv.drive_file_id && (
            <button
              onClick={() =>
                window.open(
                  `https://drive.google.com/file/d/${inv.drive_file_id}/preview`,
                  "_blank",
                )
              }
              style={{ ...s.btn, ...s.ghost }}
            >
              📄 Open PDF
            </button>
          )}
          <button
            onClick={() => {
              setReviewInv(rich);
              onClose();
            }}
            style={{ ...s.btn, ...s.primary }}
          >
            ✏️ Review & Edit
          </button>
          <button
            onClick={() => {
              setVerifyInv(rich);
              onClose();
            }}
            style={{ ...s.btn, background: "#059669", color: "#fff" }}
          >
            🛡️ Verify Compliance
          </button>
        </div>

        {linkedFiles.length > 0 && (
          <>
            <p style={s.section}>Queue for Rescan</p>
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {linkedFiles.map(({ label, fid }) => {
                const queued = rescanSet.has(fid);
                return (
                  <div
                    key={fid}
                    style={{
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "space-between",
                      padding: "8px 12px",
                      borderRadius: 6,
                      fontSize: 12,
                      background: queued ? "#EEF2FF" : "#F8FAFC",
                      border: queued
                        ? "1px solid #C7D2FE"
                        : "1px solid #E2E8F0",
                    }}
                  >
                    <span
                      style={{
                        color: queued ? "#4F46E5" : "#334155",
                        fontWeight: queued ? 600 : 400,
                      }}
                    >
                      {label}
                      {queued && (
                        <span
                          style={{
                            marginLeft: 8,
                            fontSize: 10,
                            color: "#4F46E5",
                            fontWeight: 600,
                          }}
                        >
                          ● Queued
                        </span>
                      )}
                    </span>
                    <button
                      onClick={() => toggleFileRescan(fid)}
                      style={{
                        ...s.btn,
                        fontSize: 11,
                        padding: "4px 10px",
                        background: queued ? "#4F46E5" : "#64748B",
                        color: "#fff",
                      }}
                    >
                      {queued ? "Remove" : "Queue"}
                    </button>
                  </div>
                );
              })}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

export default function InvoiceList() {
  const { getToken, isLoaded, isSignedIn } = useAuth();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [advFilters, setAdvFilters] = useState(null);
  const [overdueOnly, setOverdueOnly] = useState(false);
  const [page, setPage] = useState(1);
  const [sortBy, setSortBy] = useState("processed_at");
  const [sortDir, setSortDir] = useState("desc");
  const [panelInv, setPanelInv] = useState(null);
  const [reviewInv, setReviewInv] = useState(null);
  const [verifyInv, setVerifyInv] = useState(null);
  const [hsnProfile, setHsnProfile] = useState(null);
  const [rescanSet, setRescanSet] = useState(new Set());
  const [rescanning, setRescanning] = useState(false);
  const [rescanMsg, setRescanMsg] = useState(null);
  const [markingPaidId, setMarkingPaidId] = useState(null);

  function applyClientFilters(invoices) {
    if (!advFilters) return invoices;
    const f = advFilters;
    return invoices.filter((inv) => {
      if (
        f.invoice_number &&
        !String(inv.invoice_number || "")
          .toLowerCase()
          .includes(f.invoice_number.toLowerCase())
      )
        return false;
      if (
        f.waybill_number &&
        !String(inv.waybill_number || "")
          .toLowerCase()
          .includes(f.waybill_number.toLowerCase())
      )
        return false;
      if (
        f.grn_number &&
        !String(inv.grn_number || "")
          .toLowerCase()
          .includes(f.grn_number.toLowerCase())
      )
        return false;
      if (
        f.mrn_number &&
        !String(inv.mrn_number || "")
          .toLowerCase()
          .includes(f.mrn_number.toLowerCase())
      )
        return false;
      if (
        f.amount_min != null &&
        (inv.total_amount == null || Number(inv.total_amount) < f.amount_min)
      )
        return false;
      if (
        f.amount_max != null &&
        (inv.total_amount == null || Number(inv.total_amount) > f.amount_max)
      )
        return false;
      return true;
    });
  }

  const fetchInvoices = useCallback(async () => {
    if (!isLoaded || !isSignedIn) return;
    setLoading(true);
    setError(null);
    try {
      const tok = await getToken({ skipCache: true });
      const f = advFilters || {};
      const p = new URLSearchParams({
        page,
        page_size: 50,
        sort_by: sortBy,
        sort_dir: sortDir,
      });
      if (f.search) p.set("search", f.search);
      if (f.status) p.set("status", f.status);
      if (f.vendor_gstin) p.set("vendor_gstin", f.vendor_gstin);
      if (f.po_number) p.set("po_number", f.po_number);
      if (f.paid != null) p.set("paid", String(f.paid));
      if (f.overdue_only || overdueOnly) p.set("overdue_only", "true");
      if (f.date_from) p.set("date_from", f.date_from);
      if (f.date_to) p.set("date_to", f.date_to);
      const res = await fetch(`${API_BASE}/invoices?${p}`, {
        headers: { Authorization: `Bearer ${tok}` },
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setData(await res.json());
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [
    getToken,
    page,
    sortBy,
    sortDir,
    advFilters,
    overdueOnly,
    isLoaded,
    isSignedIn,
  ]);

  useEffect(() => {
    fetchInvoices();
  }, [fetchInvoices]);

  const fetchHsnProfile = useCallback(async () => {
    try {
      const tok = await getToken({ skipCache: true });
      const res = await fetch(`${API_BASE}/org/hsn-profile`, {
        headers: { Authorization: `Bearer ${tok}` },
      });
      if (res.ok) setHsnProfile(await res.json());
    } catch {}
  }, [getToken]);

  useEffect(() => {
    fetchHsnProfile();
  }, [fetchHsnProfile]);

  async function markPaid(invoiceId) {
    setMarkingPaidId(invoiceId);
    try {
      const tok = await getToken({ skipCache: true });
      const res = await fetch(`${API_BASE}/invoices/${invoiceId}/mark-paid`, {
        method: "PATCH",
        headers: { Authorization: `Bearer ${tok}` },
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      await fetchInvoices();
    } catch (e) {
      console.error("mark-paid failed:", e.message);
    } finally {
      setMarkingPaidId(null);
    }
  }

  function toggleInvoiceRescan(inv) {
    const ids = allFileIds(inv);
    if (!ids.length) return;
    setRescanSet((prev) => {
      const n = new Set(prev);
      const allIn = ids.every((fid) => n.has(fid));
      ids.forEach((fid) => (allIn ? n.delete(fid) : n.add(fid)));
      return n;
    });
  }

  async function rescanSelected() {
    if (rescanSet.size === 0) return;
    setRescanning(true);
    setRescanMsg(null);
    try {
      const tok = await getToken({ skipCache: true });
      const res = await fetch(`${API_BASE}/invoices/rescan`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${tok}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ drive_file_ids: [...rescanSet] }),
      });
      const d = await res.json();
      if (!res.ok) throw new Error(d.detail || `HTTP ${res.status}`);
      setRescanMsg(`Rescanned ${d.rescanned} file(s)`);
      setRescanSet(new Set());
      fetchInvoices();
    } catch (e) {
      setRescanMsg(`Rescan failed: ${e.message}`);
    } finally {
      setRescanning(false);
    }
  }

  function handleSort(col) {
    if (sortBy === col) setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    else {
      setSortBy(col);
      setSortDir("desc");
    }
    setPage(1);
  }

  const COLS = [
    { key: null, label: "", w: 32 },
    { key: "vendor_name", label: "Vendor", sort: true },
    { key: "invoice_date", label: "Inv Date", sort: true },
    { key: "po_date", label: "PO Date" },
    { key: "po_number", label: "PO No." },
    { key: "waybill_no", label: "Waybill" },
    { key: "grn_no", label: "GRN" },
    { key: "mrn_no", label: "MRN" },
    { key: "total_amount", label: "Amount", sort: true },
    { key: "pay_by", label: "Pay by" },
    { key: "incoterm", label: "Incoterm" },
    { key: "docs", label: "PWGM" },
    { key: "status", label: "Status", sort: true },
    { key: "confidence", label: "Conf.", sort: true },
  ];

  const invoices = applyClientFilters(data?.invoices ?? []);
  const totalPages = data?.total_pages ?? 1;
  const overdueCount = invoices.filter(
    (inv) => resolveIsOverdue(inv) && !inv.is_paid,
  ).length;
  const isOverdueFiltered = !!(advFilters?.overdue_only || overdueOnly);

  return (
    <div style={s.wrap}>
      <div style={s.header}>
        <div>
          <h1 style={s.h1}>Invoices Command Center</h1>
          <p style={{ margin: "2px 0 0", fontSize: 13, color: "#64748B" }}>
            Track document chains, verify ITC eligibility, and resolve
            exceptions.
          </p>
        </div>
        <button
          onClick={fetchInvoices}
          style={{
            ...s.btn,
            ...s.ghost,
          }}
        >
          🔄 Refresh Data
        </button>
      </div>

      <AdvancedSearch
        onSearch={(filters) => {
          setAdvFilters(filters);
          setOverdueOnly(filters.overdue_only || false);
          setPage(1);
        }}
        onClear={() => {
          setAdvFilters(null);
          setOverdueOnly(false);
          setPage(1);
        }}
      />

      {!isOverdueFiltered && (
        <OverdueBanner
          count={overdueCount}
          onFilter={() => {
            setAdvFilters((f) => ({ ...(f || {}), overdue_only: true }));
            setOverdueOnly(true);
            setPage(1);
          }}
        />
      )}

      {rescanSet.size > 0 && (
        <div style={s.rescanBar}>
          <span style={{ fontSize: 12, color: "#4F46E5", fontWeight: 600 }}>
            {rescanSet.size} file{rescanSet.size > 1 ? "s" : ""} queued for
            rescan
          </span>
          <button
            onClick={rescanSelected}
            disabled={rescanning}
            style={{ ...s.btn, ...s.primary }}
          >
            {rescanning ? "Rescanning…" : "⚡ Rescan Now"}
          </button>
          <button
            onClick={() => setRescanSet(new Set())}
            style={{ ...s.btn, ...s.ghost }}
          >
            Clear selection
          </button>
          {rescanMsg && (
            <span style={{ fontSize: 12, color: "#059669", fontWeight: 600 }}>
              {rescanMsg}
            </span>
          )}
        </div>
      )}

      {loading && (
        <div
          style={{
            padding: "40px 24px",
            textAlign: "center",
            color: "#64748B",
          }}
        >
          Loading invoices…
        </div>
      )}
      {error && (
        <div
          style={{
            padding: "20px 24px",
            color: "#E11D48",
            background: "#FFF1F2",
            margin: "16px 24px",
            borderRadius: 8,
          }}
        >
          Error loading invoices: {error}
        </div>
      )}
      {!loading && !error && invoices.length === 0 && (
        <div
          style={{
            padding: "40px 24px",
            textAlign: "center",
            color: "#64748B",
          }}
        >
          {isOverdueFiltered
            ? "No overdue invoices found — all accounts clear!"
            : "No invoices match the current filter criteria."}
        </div>
      )}

      {!loading && invoices.length > 0 && (
        <div
          style={{
            background: "#FFFFFF",
            borderTop: "1px solid #E2E8F0",
            borderBottom: "1px solid #E2E8F0",
            overflowX: "auto",
          }}
        >
          <table style={s.table}>
            <thead>
              <tr>
                {COLS.map((col) => (
                  <th
                    key={col.label}
                    style={{
                      ...s.th,
                      width: col.w || undefined,
                      cursor: col.sort ? "pointer" : "default",
                    }}
                    onClick={() => col.sort && col.key && handleSort(col.key)}
                  >
                    {col.label}
                    {col.sort &&
                      col.key &&
                      (sortBy === col.key ? (
                        sortDir === "asc" ? (
                          " ↑"
                        ) : (
                          " ↓"
                        )
                      ) : (
                        <span style={{ opacity: 0.3 }}> ↕</span>
                      ))}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {invoices.map((inv) => {
                const isPlaceholder = inv.status === "PLACEHOLDER";
                const inRescan = anyInRescan(inv, rescanSet);
                const hasAnyFile = allFileIds(inv).length > 0;
                const overdue = resolveIsOverdue(inv);
                const isMarkingThis = markingPaidId === inv.invoice_id;
                return (
                  <tr
                    key={inv.invoice_id}
                    style={{
                      cursor: "pointer",
                      background: inRescan
                        ? "#EEF2FF"
                        : overdue
                          ? "#FFF5F5"
                          : isPlaceholder
                            ? "#F8FAFC"
                            : "transparent",
                      transition: "background 0.1s ease",
                    }}
                    onMouseEnter={(e) => {
                      if (!inRescan && !isPlaceholder && !overdue)
                        e.currentTarget.style.background = "#F8FAFC";
                    }}
                    onMouseLeave={(e) => {
                      e.currentTarget.style.background = inRescan
                        ? "#EEF2FF"
                        : overdue
                          ? "#FFF5F5"
                          : isPlaceholder
                            ? "#F8FAFC"
                            : "transparent";
                    }}
                    onClick={() => setPanelInv(inv)}
                  >
                    <td
                      style={{ ...s.td, width: 32, paddingRight: 0 }}
                      onClick={(e) => {
                        e.stopPropagation();
                        toggleInvoiceRescan(inv);
                      }}
                    >
                      {hasAnyFile && (
                        <input
                          type="checkbox"
                          checked={inRescan}
                          onChange={() => {}}
                          style={{ cursor: "pointer", accentColor: "#4F46E5" }}
                        />
                      )}
                    </td>
                    <td style={s.td}>
                      <div
                        style={{
                          fontWeight: 600,
                          fontSize: 13,
                          color: "#0F172A",
                        }}
                      >
                        {inv.vendor_name ||
                          (isPlaceholder ? (
                            <em style={{ color: "#94A3B8" }}>Placeholder</em>
                          ) : (
                            "—"
                          ))}
                      </div>
                      {inv.vendor_gstin && (
                        <div
                          style={{
                            fontSize: 11,
                            color: "#64748B",
                            fontFamily: "monospace",
                          }}
                        >
                          {inv.vendor_gstin}
                        </div>
                      )}
                    </td>
                    <td
                      style={{
                        ...s.td,
                        fontSize: 12,
                        color: inv.invoice_date ? "#334155" : "#94A3B8",
                        whiteSpace: "nowrap",
                      }}
                    >
                      {fmtDate(inv.invoice_date)}
                    </td>
                    <td
                      style={{
                        ...s.td,
                        fontSize: 12,
                        color: inv.po_date ? "#334155" : "#94A3B8",
                        whiteSpace: "nowrap",
                      }}
                    >
                      {fmtDate(inv.po_date)}
                    </td>
                    <td
                      style={{
                        ...s.td,
                        fontFamily: "monospace",
                        fontSize: 12,
                        color: inv.po_number ? "#0F172A" : "#94A3B8",
                      }}
                    >
                      {inv.po_number || "—"}
                    </td>
                    <td
                      style={{
                        ...s.td,
                        fontFamily: "monospace",
                        fontSize: 12,
                        color: inv.waybill_number ? "#0F172A" : "#94A3B8",
                      }}
                    >
                      {inv.waybill_number || "—"}
                    </td>
                    <td
                      style={{
                        ...s.td,
                        fontFamily: "monospace",
                        fontSize: 12,
                        color: inv.grn_number ? "#0F172A" : "#94A3B8",
                      }}
                    >
                      {inv.grn_number || "—"}
                    </td>
                    <td
                      style={{
                        ...s.td,
                        fontFamily: "monospace",
                        fontSize: 12,
                        color: inv.mrn_number ? "#0F172A" : "#94A3B8",
                      }}
                    >
                      {inv.mrn_number || "—"}
                    </td>
                    <td
                      style={{
                        ...s.td,
                        textAlign: "right",
                        whiteSpace: "nowrap",
                        fontWeight: 600,
                        color: inv.total_amount ? "#0F172A" : "#94A3B8",
                      }}
                    >
                      {fmtAmount(inv.total_amount)}
                    </td>
                    <td style={{ ...s.td, whiteSpace: "nowrap" }}>
                      <PayByCell
                        inv={inv}
                        onMarkPaid={
                          overdue && !inv.is_paid
                            ? () => markPaid(inv.invoice_id)
                            : null
                        }
                        markingPaid={isMarkingThis}
                      />
                    </td>
                    <td
                      style={{
                        ...s.td,
                        fontSize: 12,
                        color:
                          inv.po_incoterm || inv.po_incoterm_raw
                            ? "#334155"
                            : "#94A3B8",
                      }}
                    >
                      {inv.po_incoterm || inv.po_incoterm_raw || "—"}
                    </td>
                    <td
                      style={{ ...s.td, whiteSpace: "nowrap" }}
                      onClick={(e) => e.stopPropagation()}
                    >
                      <DocChainBadge inv={inv} />
                    </td>
                    <td style={s.td}>
                      <StatusBadge status={inv.status} />
                    </td>
                    <td
                      style={{
                        ...s.td,
                        color: "#64748B",
                        textAlign: "right",
                        fontWeight: 500,
                      }}
                    >
                      {fmtConf(inv.confidence)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {!loading && totalPages > 1 && (
        <div
          style={{
            display: "flex",
            gap: 12,
            padding: "16px 24px",
            alignItems: "center",
            fontSize: 13,
            background: "#FFFFFF",
            borderTop: "1px solid #E2E8F0",
          }}
        >
          <button
            style={{ ...s.btn, ...s.ghost }}
            disabled={page <= 1}
            onClick={() => setPage((p) => p - 1)}
          >
            ← Previous
          </button>
          <span style={{ color: "#64748B", fontWeight: 500 }}>
            Page {page} of {totalPages}
            {data?.total_count != null &&
              ` · ${data.total_count} total invoices`}
          </span>
          <button
            style={{ ...s.btn, ...s.ghost }}
            disabled={page >= totalPages}
            onClick={() => setPage((p) => p + 1)}
          >
            Next →
          </button>
        </div>
      )}

      {panelInv && (
        <SidePanel
          inv={panelInv}
          onClose={() => setPanelInv(null)}
          getToken={getToken}
          hsnProfile={hsnProfile}
          onHsnProfileUpdate={fetchHsnProfile}
          rescanSet={rescanSet}
          setRescanSet={setRescanSet}
          setReviewInv={setReviewInv}
          setVerifyInv={setVerifyInv}
          onMarkPaid={markPaid}
        />
      )}
      {reviewInv && (
        <ReviewModal
          invoiceId={reviewInv.invoice_id}
          data={reviewInv}
          getToken={getToken}
          onClose={() => {
            setReviewInv(null);
            fetchInvoices();
          }}
          onSaved={() => {
            setReviewInv(null);
            fetchInvoices();
          }}
        />
      )}
      {verifyInv && (
        <VerifyModal
          invoiceId={verifyInv.invoice_id}
          data={verifyInv}
          getToken={getToken}
          onClose={() => {
            setVerifyInv(null);
            fetchInvoices();
          }}
          onVerified={() => {
            setVerifyInv(null);
            fetchInvoices();
          }}
        />
      )}
    </div>
  );
}
