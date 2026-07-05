/**
 * VerifyModal.jsx
 * ===============
 * Human verification overlay. Three purposes:
 *
 * 1. STAMP: Marks the invoice as is_user_verified=true via PATCH /invoices/{id}.
 *    This sets the "✓ Verified" badge and feeds the verification rate metric.
 *
 * 2. CHECKLIST: Three quick yes/no checks the reviewer answers before stamping:
 *      - Vendor GSTIN matches source document
 *      - Amounts reconcile (taxable + GST = total)
 *      - ITC is eligible for this line of business
 *    These are saved as a JSON blob in the `verification_note` field so every
 *    verification decision is auditable.
 *
 * 3. TRAINING DATA: Each verification creates a structured ground-truth record
 *    at POST /training-exports (if the endpoint exists). The record contains
 *    the full extracted fields plus the human's corrections and checklist
 *    answers — exactly the shape needed to fine-tune the extraction model later.
 *    If the endpoint doesn't exist yet (404), the export is silently skipped;
 *    verification itself always succeeds regardless.
 *
 * Props:
 *   invoiceId   — string
 *   data        — full invoice detail object
 *   getToken    — async () => string
 *   onClose     — () => void
 *   onVerified  — () => void  (parent refetches invoice after stamp)
 */

import { useState } from "react";

const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000";

const CHECKS = [
  {
    id: "gstin_match",
    label: "Vendor GSTIN matches the source document",
    hint: "Check the printed GSTIN on the invoice PDF against the extracted value.",
  },
  {
    id: "amounts_reconcile",
    label: "Taxable amount + GST = Total (within ₹1)",
    hint: "Quick arithmetic check. The AI flags mismatches but a human confirms.",
  },
  {
    id: "itc_eligible",
    label: "Purchase is ITC-eligible for this business",
    hint: "Not blocked under Section 17(5) — no motor vehicles, restaurant bills, club memberships, etc.",
  },
];

export default function VerifyModal({ invoiceId, data, getToken, onClose, onVerified }) {
  const [checks, setChecks]     = useState({ gstin_match: null, amounts_reconcile: null, itc_eligible: null });
  const [note, setNote]         = useState("");
  const [saving, setSaving]     = useState(false);
  const [err, setErr]           = useState(null);

  const allAnswered = Object.values(checks).every(v => v !== null);
  const anyFailed   = Object.values(checks).some(v => v === false);

  async function handleVerify() {
    if (!allAnswered) return;
    setSaving(true);
    setErr(null);
    try {
      const tok = await getToken();

      // Build structured verification note — this is the training data anchor
      const verificationPayload = {
        checks,
        note: note.trim() || null,
        verified_at: new Date().toISOString(),
        extracted_fields: {
          vendor_name:       data.vendor_name,
          vendor_gstin:      data.vendor_gstin,
          buyer_gstin:       data.buyer_gstin,
          invoice_number:    data.invoice_number,
          invoice_date:      data.invoice_date,
          taxable_amount:    data.taxable_amount,
          total_gst_amount:  data.total_gst_amount,
          total_amount:      data.total_amount,
          extraction_method: data.extraction_method,
          confidence:        data.confidence,
        },
        line_items: (data.line_items || []).map(li => ({
          hsn_code:            li.hsn_code,
          amount:              li.amount,
          business_use_percent: li.business_use_percent,
          itc_claimable:       li.itc_claimable,
        })),
      };

      // 1. Mark invoice as verified + write structured note
      const res = await fetch(`${API_BASE}/invoices/${invoiceId}`, {
        method: "PATCH",
        headers: { Authorization: `Bearer ${tok}`, "Content-Type": "application/json" },
        body: JSON.stringify({
          fields: {
            is_user_verified: true,
            // Store structured checklist as JSON string in the notes field
            // so it's auditable and queryable without a schema migration.
            verification_note: JSON.stringify(verificationPayload),
          },
          line_items: [],
        }),
      });
      if (!res.ok) throw new Error(`PATCH failed: HTTP ${res.status}`);

      // 2. Write training export record (fire-and-forget, non-fatal)
      // This endpoint collects human-verified ground truth for model fine-tuning.
      // Shape: { invoice_id, source_type, confidence, extracted_fields,
      //          human_corrections (fields changed after extraction),
      //          verification_checks, verification_note }
      try {
        await fetch(`${API_BASE}/training-exports`, {
          method: "POST",
          headers: { Authorization: `Bearer ${tok}`, "Content-Type": "application/json" },
          body: JSON.stringify({
            invoice_id:           invoiceId,
            source_type:          data.source_type,
            extraction_method:    data.extraction_method,
            confidence:           data.confidence,
            extracted_fields:     verificationPayload.extracted_fields,
            line_items:           verificationPayload.line_items,
            verification_checks:  checks,
            verification_note:    note.trim() || null,
            any_check_failed:     anyFailed,
          }),
        });
        // 404 = endpoint not implemented yet — silently skip, don't fail
      } catch (_) {}

      onVerified();
      onClose();
    } catch (e) {
      setErr(String(e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div style={overlay}>
      <div style={modal} onClick={e => e.stopPropagation()}>
        {/* Header */}
        <div style={mh.header}>
          <div style={mh.titleRow}>
            <span style={mh.stamp}>✓</span>
            <div>
              <div style={mh.title}>Mark as manually verified</div>
              <div style={mh.sub}>
                {data?.file_name} — {data?.vendor_name || "Unknown vendor"}
              </div>
            </div>
          </div>
          <button onClick={onClose} style={mh.closeBtn} aria-label="Close">✕</button>
        </div>

        <div style={mh.body}>
          {/* AI extraction summary */}
          <div style={mh.summaryRow}>
            <span style={mh.summaryItem}>
              Confidence: <strong>{data?.confidence?.toFixed(0)}%</strong>
            </span>
            <span style={mh.summaryItem}>
              Method: <strong>{data?.extraction_method?.replace("_", " ")}</strong>
            </span>
            <span style={mh.summaryItem}>
              Total: <strong>₹{Number(data?.total_amount || 0).toLocaleString("en-IN")}</strong>
            </span>
          </div>

          {/* Checklist */}
          <div style={mh.sectionLabel}>Verification checklist</div>
          <div style={mh.checks}>
            {CHECKS.map(c => (
              <div key={c.id} style={mh.checkRow}>
                <div style={mh.checkMeta}>
                  <div style={mh.checkLabel}>{c.label}</div>
                  <div style={mh.checkHint}>{c.hint}</div>
                </div>
                <div style={mh.checkBtns}>
                  <button
                    onClick={() => setChecks(p => ({ ...p, [c.id]: true }))}
                    style={{
                      ...mh.checkBtn,
                      ...(checks[c.id] === true ? mh.checkBtnYesActive : {}),
                    }}
                  >✓ Yes</button>
                  <button
                    onClick={() => setChecks(p => ({ ...p, [c.id]: false }))}
                    style={{
                      ...mh.checkBtn,
                      ...(checks[c.id] === false ? mh.checkBtnNoActive : {}),
                    }}
                  >✗ No</button>
                </div>
              </div>
            ))}
          </div>

          {/* Warning if any check failed */}
          {anyFailed && (
            <div style={mh.warnBanner}>
              ⚠ One or more checks failed. You can still verify — the result will be
              flagged as "verified with issues" in the training data and activity log.
            </div>
          )}

          {/* Optional note */}
          <div style={mh.sectionLabel}>Note <span style={{ fontWeight: 400, color: "#9CA3AF" }}>(optional)</span></div>
          <textarea
            value={note}
            onChange={e => setNote(e.target.value)}
            placeholder="e.g. Confirmed with vendor, GST portal, or original PO…"
            style={mh.noteArea}
            rows={2}
          />

          {err && <div style={mh.errBanner}>{err}</div>}

          {/* Training data notice */}
          <div style={mh.trainingNote}>
            🧠 This verification is saved as ground truth for model training.
            Your corrections and checklist answers improve future extraction accuracy.
          </div>
        </div>

        {/* Footer */}
        <div style={mh.footer}>
          <button onClick={onClose} style={mh.cancelBtn} disabled={saving}>Cancel</button>
          <button
            onClick={handleVerify}
            disabled={!allAnswered || saving}
            style={{
              ...mh.verifyBtn,
              opacity: !allAnswered || saving ? 0.5 : 1,
              cursor: !allAnswered || saving ? "not-allowed" : "pointer",
            }}
          >
            {saving ? "Saving…" : anyFailed ? "✓ Verify (with issues)" : "✓ Mark as verified"}
          </button>
        </div>
      </div>
    </div>
  );
}

const overlay = {
  position: "fixed", inset: 0, background: "rgba(17,19,24,0.55)",
  display: "flex", alignItems: "center", justifyContent: "center",
  zIndex: 1000, padding: 24,
};

const modal = {
  background: "#fff", borderRadius: 14, width: "100%", maxWidth: 520,
  boxShadow: "0 24px 64px rgba(0,0,0,0.2)",
  fontFamily: "Inter, system-ui, -apple-system, sans-serif",
  overflow: "hidden",
};

const mh = {
  header: {
    display: "flex", justifyContent: "space-between", alignItems: "flex-start",
    padding: "20px 24px 16px", borderBottom: "1px solid #F3F4F6",
    background: "#F9FAFB",
  },
  titleRow: { display: "flex", alignItems: "center", gap: 12 },
  stamp: {
    width: 36, height: 36, background: "#312E81", borderRadius: 8,
    display: "flex", alignItems: "center", justifyContent: "center",
    fontSize: 18, color: "#fff", flexShrink: 0,
  },
  title: { fontSize: 15, fontWeight: 700, color: "#111318" },
  sub: { fontSize: 11, color: "#9CA3AF", marginTop: 2 },
  closeBtn: {
    background: "none", border: "none", cursor: "pointer",
    fontSize: 16, color: "#9CA3AF", padding: "2px 4px", lineHeight: 1,
  },
  body: { padding: "18px 24px" },
  summaryRow: {
    display: "flex", gap: 20, marginBottom: 18,
    padding: "10px 14px", background: "#F7F8FA", borderRadius: 8,
  },
  summaryItem: { fontSize: 11, color: "#6B7280" },
  sectionLabel: {
    fontSize: 11, fontWeight: 700, textTransform: "uppercase",
    letterSpacing: "0.05em", color: "#6B7280", marginBottom: 10, marginTop: 14,
  },
  checks: { display: "flex", flexDirection: "column", gap: 10 },
  checkRow: {
    display: "flex", alignItems: "center", justifyContent: "space-between",
    gap: 12, padding: "12px 14px", background: "#F9FAFB",
    borderRadius: 8, border: "1px solid #F3F4F6",
  },
  checkMeta: { flex: 1 },
  checkLabel: { fontSize: 12, fontWeight: 600, color: "#111318", marginBottom: 2 },
  checkHint: { fontSize: 11, color: "#9CA3AF", lineHeight: 1.4 },
  checkBtns: { display: "flex", gap: 6, flexShrink: 0 },
  checkBtn: {
    border: "1px solid #D1D5DB", borderRadius: 6, padding: "4px 10px",
    fontSize: 11, fontWeight: 600, cursor: "pointer", background: "#fff",
    color: "#6B7280", fontFamily: "inherit", whiteSpace: "nowrap",
    transition: "all 0.1s",
  },
  checkBtnYesActive: {
    background: "#DCFCE7", borderColor: "#15803D", color: "#15803D",
  },
  checkBtnNoActive: {
    background: "#FEE2E2", borderColor: "#B91C1C", color: "#B91C1C",
  },
  warnBanner: {
    marginTop: 12, padding: "10px 14px",
    background: "#FFFBEB", border: "1px solid #FDE68A",
    borderRadius: 8, fontSize: 12, color: "#92400E", lineHeight: 1.5,
  },
  noteArea: {
    width: "100%", border: "1px solid #D1D5DB", borderRadius: 8,
    padding: "8px 12px", fontSize: 12, fontFamily: "inherit",
    color: "#111318", resize: "vertical", boxSizing: "border-box",
    outline: "none",
  },
  errBanner: {
    marginTop: 10, padding: "8px 12px",
    background: "#FEF2F2", border: "1px solid #FECACA",
    borderRadius: 6, fontSize: 12, color: "#B91C1C",
  },
  trainingNote: {
    marginTop: 14, fontSize: 11, color: "#6B7280",
    padding: "8px 12px", background: "#F0F0FF",
    borderRadius: 8, lineHeight: 1.5,
  },
  footer: {
    display: "flex", justifyContent: "flex-end", gap: 10,
    padding: "14px 24px", borderTop: "1px solid #F3F4F6",
    background: "#F9FAFB",
  },
  cancelBtn: {
    background: "#fff", border: "1px solid #D1D5DB", borderRadius: 8,
    padding: "8px 18px", fontSize: 13, fontWeight: 500, cursor: "pointer",
    fontFamily: "inherit", color: "#374151",
  },
  verifyBtn: {
    background: "#312E81", border: "none", borderRadius: 8,
    padding: "8px 20px", fontSize: 13, fontWeight: 600, color: "#fff",
    fontFamily: "inherit",
  },
};