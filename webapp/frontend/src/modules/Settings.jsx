import { useState, useEffect } from "react";
import { useOrganization } from "@clerk/clerk-react";

const API_BASE =
  import.meta.env.VITE_API_BASE || import.meta.env.VITE_API_BASE || "";
function FolderRow({
  label,
  hint,
  folderType,
  currentId,
  onSaved,
  authedFetch,
  syncPath,
  syncLabel,
}) {
  const [input, setInput] = useState(currentId || "");
  const [saving, setSaving] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [msg, setMsg] = useState(null);
  useEffect(() => {
    setInput(currentId || "");
  }, [currentId]);

  async function handleSave() {
    if (!input.trim()) return;
    setSaving(true);
    setMsg(null);
    try {
      const res = await authedFetch("/org/drive-folders", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          folder_type: folderType,
          folder_id: input.trim(),
        }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const d = await res.json();
      onSaved(folderType, d.folder_id);
      setMsg({ type: "ok", text: "Folder saved." });
    } catch (e) {
      setMsg({ type: "err", text: `Save failed: ${e.message}` });
    } finally {
      setSaving(false);
    }
  }

  async function handleSync() {
    setSyncing(true);
    setMsg(null);
    try {
      const res = await authedFetch(syncPath, { method: "POST" });
      const d = await res.json();
      if (!res.ok) throw new Error(d.detail || `HTTP ${res.status}`);
      const count =
        d.new_files_processed ??
        d.entries_inserted ??
        d.files_processed ??
        (Array.isArray(d.results) ? d.results.length : "?");
      setMsg({
        type: "ok",
        text: `${syncLabel} complete — ${count} processed.`,
      });
    } catch (e) {
      setMsg({ type: "err", text: `Sync failed: ${e.message}` });
    } finally {
      setSyncing(false);
    }
  }

  return (
    <div style={s.folderBlock}>
      <div style={s.folderLabel}>{label}</div>
      <p style={{ ...s.hint, marginTop: 2, marginBottom: 10 }}>{hint}</p>

      {currentId && (
        <div style={s.currentFolder}>
          <span style={s.currentLabel}>Registered</span>
          <code style={s.currentCode}>{currentId}</code>
        </div>
      )}

      <div style={s.inputRow}>
        <input
          type="text"
          placeholder="Paste Drive folder ID"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          style={s.input}
        />
        <button
          onClick={handleSave}
          disabled={saving || !input.trim()}
          style={s.primaryBtn}
        >
          {saving ? "Saving…" : "Save"}
        </button>
        {currentId && (
          <button
            onClick={handleSync}
            disabled={syncing || saving}
            style={s.secondaryBtn}
          >
            {syncing ? "Syncing…" : "Sync now"}
          </button>
        )}
      </div>

      {msg && (
        <div style={msg.type === "ok" ? s.msgOk : s.msgErr}>{msg.text}</div>
      )}
    </div>
  );
}

export default function Settings({ getToken }) {
  const [loading, setLoading] = useState(true);
  const [folders, setFolders] = useState({
    invoices: null,
    purchase_orders: null,
    waybills: null,
    grn: null,
    material_return: null,
  });
  const [bizDesc, setBizDesc] = useState("");
  const [bizDescSaved, setBizDescSaved] = useState("");
  const [bizDescSaving, setBizDescSaving] = useState(false);
  const [hsnProfile, setHsnProfile] = useState(null);
  const [hsnPreview, setHsnPreview] = useState(null);
  const [removalSet, setRemovalSet] = useState(new Set());
  const [hsnGenerating, setHsnGenerating] = useState(false);
  const [hsnApplying, setHsnApplying] = useState(false);
  const [hsnMessage, setHsnMessage] = useState(null);
  const [manualCode, setManualCode] = useState("");
  const [manualCodeType, setManualCodeType] = useState("HSN");
  const [manualDesc, setManualDesc] = useState("");
  const [manualAdding, setManualAdding] = useState(false);
  const [removingCode, setRemovingCode] = useState(null);
  const { organization } = useOrganization();
  const [deleteOrgName, setDeleteOrgName] = useState("");
  const [deletingOrg, setDeletingOrg] = useState(false);
  const [deleteOrgMsg, setDeleteOrgMsg] = useState(null);
  const [outwardHsn, setOutwardHsn] = useState([]);
  const [outwardHsnInput, setOutwardHsnInput] = useState("");
  const [outwardHsnDesc, setOutwardHsnDesc] = useState("");
  const [outwardHsnAdding, setOutwardHsnAdding] = useState(false);
  const [outwardHsnMsg, setOutwardHsnMsg] = useState(null);

  async function handleDeleteOrg() {
    if (!organization || deleteOrgName !== organization.name) return;
    setDeletingOrg(true);
    setDeleteOrgMsg(null);
    try {
      await authedFetch("/org/delete", { method: "DELETE" });
      await organization.destroy();
    } catch (e) {
      setDeleteOrgMsg(`Delete failed: ${e.message}`);
      setDeletingOrg(false);
    }
  }

  async function handleAddOutwardHsn() {
    const code = outwardHsnInput.trim().toUpperCase();
    if (!code) return;
    setOutwardHsnAdding(true);
    setOutwardHsnMsg(null);
    try {
      const res = await authedFetch("/org/outward-hsn", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          code,
          description: outwardHsnDesc.trim() || null,
        }),
      });
      const d = await res.json();
      if (!res.ok) throw new Error(d.detail || `HTTP ${res.status}`);
      setOutwardHsn(d.codes || []);
      setOutwardHsnInput("");
      setOutwardHsnDesc("");
      setOutwardHsnMsg({
        type: "ok",
        text: `${code} added to outward supply profile.`,
      });
    } catch (e) {
      setOutwardHsnMsg({ type: "err", text: `Failed: ${e.message}` });
    } finally {
      setOutwardHsnAdding(false);
    }
  }

  async function handleRemoveOutwardHsn(code) {
    try {
      const res = await authedFetch(
        `/org/outward-hsn/${encodeURIComponent(code)}`,
        { method: "DELETE" },
      );
      const d = await res.json();
      if (!res.ok) throw new Error(d.detail || `HTTP ${res.status}`);
      setOutwardHsn(d.codes || []);
    } catch (e) {
      setOutwardHsnMsg({ type: "err", text: `Remove failed: ${e.message}` });
    }
  }

  async function authedFetch(path, options = {}) {
    const tok = await getToken();
    const res = await fetch(`${API_BASE}${path}`, {
      ...options,
      headers: { ...options.headers, Authorization: `Bearer ${tok}` },
    });
    return res;
  }

  useEffect(() => {
    const load = async () => {
      try {
        const tok = await getToken();
        const h = { Authorization: `Bearer ${tok}` };
        const fd = await fetch(`${API_BASE}/org/drive-folders`, { headers: h })
          .then((r) => (r.ok ? r.json() : null))
          .catch(() => null);
        if (fd) {
          const src = fd.folders ?? fd;
          setFolders({
            invoices: src.invoices?.folder_id || null,
            purchase_orders: src.purchase_orders?.folder_id || null,
            waybills: src.waybills?.folder_id || null,
            grn: src.grn?.folder_id || null,
            material_return: src.material_return?.folder_id || null,
          });
        }
        const sd = await fetch(`${API_BASE}/org/settings`, { headers: h })
          .then((r) => (r.ok ? r.json() : null))
          .catch(() => null);
        if (sd?.business_description) {
          setBizDesc(sd.business_description);
          setBizDescSaved(sd.business_description);
        }
        const hd = await fetch(`${API_BASE}/org/hsn-profile`, { headers: h })
          .then((r) => (r.ok ? r.json() : null))
          .catch(() => null);
        if (hd?.has_profile) setHsnProfile(hd);
        const od = await fetch(`${API_BASE}/org/outward-hsn`, { headers: h })
          .then((r) => (r.ok ? r.json() : null))
          .catch(() => null);
        if (Array.isArray(od?.codes)) setOutwardHsn(od.codes);
      } finally {
        setLoading(false);
      }
    };
    load();
  }, []);
  function handleFolderSaved(type, id) {
    setFolders((prev) => ({ ...prev, [type]: id }));
  }

  async function handleSaveBizDesc() {
    if (!bizDesc.trim()) return;
    setBizDescSaving(true);
    setHsnMessage(null);
    try {
      const res = await authedFetch("/org/settings", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ business_description: bizDesc.trim() }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setBizDescSaved(bizDesc.trim());
      setHsnMessage({ type: "ok", text: "Business description saved." });
    } catch (e) {
      setHsnMessage({ type: "err", text: `Save failed: ${e.message}` });
    } finally {
      setBizDescSaving(false);
    }
  }

  async function handleGenerateHsn() {
    if (!bizDescSaved) return;
    setHsnGenerating(true);
    setHsnMessage(null);
    try {
      const res = await authedFetch("/org/hsn-profile/generate", {
        method: "POST",
      });
      const d = await res.json();
      if (!res.ok) throw new Error(d.detail || `HTTP ${res.status}`);
      setHsnPreview(d);
      setRemovalSet(new Set());
      setHsnMessage({
        type: "ok",
        text: "Preview generated — review below and click Apply to save.",
      });
    } catch (e) {
      setHsnMessage({ type: "err", text: `Generation failed: ${e.message}` });
    } finally {
      setHsnGenerating(false);
    }
  }

  async function handleApplyHsn() {
    if (!hsnPreview) return;
    setHsnApplying(true);
    setHsnMessage(null);
    try {
      const res = await authedFetch("/org/hsn-profile/apply", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          expected_codes: hsnPreview.expected_codes,
          ambiguous_codes: hsnPreview.ambiguous_codes,
          remove_codes: [...removalSet],
        }),
      });
      const d = await res.json();
      if (!res.ok) throw new Error(d.detail || `HTTP ${res.status}`);
      setHsnProfile(d);
      setHsnPreview(null);
      setRemovalSet(new Set());
      const expCount = d.expected_hsn_codes?.length ?? 0;
      const ambCount = d.ambiguous_hsn_codes?.length ?? 0;
      setHsnMessage({
        type: "ok",
        text: `Profile saved — ${expCount} expected, ${ambCount} to watch.`,
      });
    } catch (e) {
      setHsnMessage({ type: "err", text: `Apply failed: ${e.message}` });
    } finally {
      setHsnApplying(false);
    }
  }

  async function handleAddManualCode() {
    const code = manualCode.trim().toUpperCase();
    if (!code) return;
    setManualAdding(true);
    setHsnMessage(null);
    try {
      const res = await authedFetch("/org/hsn-profile/codes", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          code,
          code_type: manualCodeType,
          description: manualDesc.trim() || null,
        }),
      });
      const d = await res.json();
      if (!res.ok) throw new Error(d.detail || `HTTP ${res.status}`);
      setHsnProfile(d);
      setManualCode("");
      setManualDesc("");
      setHsnMessage({ type: "ok", text: `Code ${code} added.` });
    } catch (e) {
      setHsnMessage({ type: "err", text: `Add failed: ${e.message}` });
    } finally {
      setManualAdding(false);
    }
  }

  async function handleRemoveCode(code) {
    setRemovingCode(code);
    setHsnMessage(null);
    try {
      const res = await authedFetch(
        `/org/hsn-profile/codes/${encodeURIComponent(code)}`,
        { method: "DELETE" },
      );
      const d = await res.json();
      if (!res.ok) throw new Error(d.detail || `HTTP ${res.status}`);
      setHsnProfile(d);
    } catch (e) {
      setHsnMessage({ type: "err", text: `Remove failed: ${e.message}` });
    } finally {
      setRemovingCode(null);
    }
  }

  if (loading) {
    return (
      <div
        style={{
          padding: 40,
          color: "#94a3b8",
          fontSize: 13,
          background: "#020617",
          minHeight: "100vh",
        }}
      >
        Loading settings…
      </div>
    );
  }

  return (
    <div style={s.root}>
      <div style={s.card}>
        <h2 style={s.heading}>Settings</h2>

        {/* ── Drive folders ─────────────────────────────────────────────── */}
        <div style={s.section}>
          <div style={s.sectionTitle}>Google Drive folders</div>
          <p style={s.hint}>
            Paste each folder's Drive ID and click Save. Once saved, use "Sync
            now" to pull files into the system. The service account must have
            Viewer access to each folder (see instructions below).
          </p>

          <FolderRow
            label="Invoices"
            hint="Purchase invoices in PDF or image format."
            folderType="invoices"
            currentId={folders.invoices}
            onSaved={handleFolderSaved}
            authedFetch={authedFetch}
            syncPath="/drive/sync"
            syncLabel="Invoice sync"
          />
          <FolderRow
            label="Purchase Orders"
            hint="PO documents matched against invoices."
            folderType="purchase_orders"
            currentId={folders.purchase_orders}
            onSaved={handleFolderSaved}
            authedFetch={authedFetch}
            syncPath="/purchase-orders/sync"
            syncLabel="PO sync"
          />
          <FolderRow
            label="Waybills"
            hint="Transport / e-way bill documents."
            folderType="waybills"
            currentId={folders.waybills}
            onSaved={handleFolderSaved}
            authedFetch={authedFetch}
            syncPath="/waybills/sync"
            syncLabel="Waybill sync"
          />
          <FolderRow
            label="GRN"
            hint="Goods Receipt Notes confirming delivery."
            folderType="grn"
            currentId={folders.grn}
            onSaved={handleFolderSaved}
            authedFetch={authedFetch}
            syncPath="/grn/sync"
            syncLabel="GRN sync"
          />
          <FolderRow
            label="Material Returns"
            hint="Material Return Notes for rejected / returned goods."
            folderType="material_return"
            currentId={folders.material_return}
            onSaved={handleFolderSaved}
            authedFetch={authedFetch}
            syncPath="/material-returns/sync"
            syncLabel="MR sync"
          />
        </div>

        {/* ── Issue 8: Outward supply HSN codes ────────────────────────── */}
        <div style={s.section}>
          <div style={s.sectionTitle}>
            What your business sells (outward supply)
          </div>
          <p style={s.hint}>
            Add the HSN/SAC codes for goods or services{" "}
            <strong>your business sells</strong>. These are used to determine
            ITC eligibility — the GST you pay on purchases is only claimable as
            Input Tax Credit if it relates to your taxable outward supply. This
            is separate from the vendor HSN profile below, which is derived from
            your purchase invoices.
          </p>

          <div
            style={{
              display: "flex",
              gap: 8,
              alignItems: "center",
              flexWrap: "wrap",
              marginBottom: 12,
            }}
          >
            <input
              type="text"
              placeholder="HSN/SAC code e.g. 9403"
              value={outwardHsnInput}
              onChange={(e) => setOutwardHsnInput(e.target.value)}
              style={{
                ...s.input,
                width: 140,
                flex: "none",
                fontFamily: "monospace",
              }}
            />
            <input
              type="text"
              placeholder="Description (optional)"
              value={outwardHsnDesc}
              onChange={(e) => setOutwardHsnDesc(e.target.value)}
              style={{ ...s.input, flex: 1, minWidth: 160 }}
            />
            <button
              onClick={handleAddOutwardHsn}
              disabled={outwardHsnAdding || !outwardHsnInput.trim()}
              style={s.primaryBtn}
            >
              {outwardHsnAdding ? "Adding…" : "Add"}
            </button>
          </div>

          {outwardHsn.length > 0 ? (
            <div
              style={{
                display: "flex",
                flexWrap: "wrap",
                gap: 6,
                marginTop: 6,
              }}
            >
              {outwardHsn.map((item) => (
                <div
                  key={item.code}
                  title={item.description || item.code}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 6,
                    fontFamily: "monospace",
                    fontSize: 11,
                    background: "rgba(99, 102, 241, 0.1)",
                    color: "#818cf8",
                    borderRadius: 6,
                    padding: "3px 6px 3px 9px",
                    border: "1px solid rgba(99, 102, 241, 0.25)",
                  }}
                >
                  {item.code}
                  {item.description && (
                    <span
                      style={{
                        fontSize: 10,
                        color: "#94a3b8",
                        fontFamily: "Inter,system-ui,sans-serif",
                        maxWidth: 120,
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                        whiteSpace: "nowrap",
                      }}
                    >
                      &nbsp;{item.description}
                    </span>
                  )}
                  <button
                    onClick={() => handleRemoveOutwardHsn(item.code)}
                    style={{
                      background: "none",
                      border: "none",
                      cursor: "pointer",
                      padding: "0 2px",
                      color: "#818cf8",
                      fontSize: 14,
                      lineHeight: 1,
                      opacity: 0.8,
                    }}
                  >
                    ×
                  </button>
                </div>
              ))}
            </div>
          ) : (
            <p style={{ fontSize: 12, color: "#94a3b8", margin: "4px 0 0" }}>
              No outward supply codes added yet. Add at least one to enable ITC
              eligibility checks.
            </p>
          )}

          {outwardHsnMsg && (
            <div
              style={{
                ...(outwardHsnMsg.type === "ok" ? s.msgOk : s.msgErr),
                marginTop: 12,
              }}
            >
              {outwardHsnMsg.text}
            </div>
          )}
        </div>

        {/* ── Vendor HSN profile (what vendors supply to us) ────────────── */}
        <div style={s.section}>
          <div style={s.sectionTitle}>
            Vendor supply profile (purchase HSN codes)
          </div>
          <p style={s.hint}>
            Describe your business in one sentence. Used to generate a list of
            HSN/SAC codes expected on your <strong>purchase invoices</strong>{" "}
            (what vendors supply to you — not what you sell). Line items are
            then automatically badged as expected, ambiguous, or unknown. This
            is the <em>vendor</em> profile, not your outward supply profile
            above.
          </p>

          <div
            style={{
              display: "flex",
              gap: 8,
              alignItems: "flex-start",
              flexWrap: "wrap",
              marginBottom: 12,
            }}
          >
            <textarea
              rows={2}
              placeholder="e.g. furniture manufacturing and retail shop selling chairs, tables and wooden fixtures"
              value={bizDesc}
              onChange={(e) => setBizDesc(e.target.value)}
              style={{
                ...s.input,
                flex: 1,
                minWidth: 240,
                resize: "vertical",
                fontFamily: "inherit",
                lineHeight: 1.5,
              }}
            />
            <button
              onClick={handleSaveBizDesc}
              disabled={
                bizDescSaving ||
                !bizDesc.trim() ||
                bizDesc.trim() === bizDescSaved
              }
              style={s.primaryBtn}
            >
              {bizDescSaving ? "Saving…" : "Save"}
            </button>
          </div>

          {bizDescSaved && (
            <button
              onClick={handleGenerateHsn}
              disabled={hsnGenerating}
              style={s.secondaryBtn}
            >
              {hsnGenerating
                ? "Generating preview…"
                : hsnProfile?.has_profile
                  ? "Regenerate HSN profile"
                  : "Generate HSN profile"}
            </button>
          )}

          {hsnPreview && (
            <div
              style={{
                marginTop: 16,
                background: "rgba(59, 130, 246, 0.08)",
                border: "1px solid rgba(59, 130, 246, 0.25)",
                borderRadius: 10,
                padding: "16px 18px",
              }}
            >
              <div
                style={{
                  fontWeight: 700,
                  fontSize: 13,
                  color: "#60a5fa",
                  marginBottom: 4,
                }}
              >
                Preview — not saved yet
              </div>
              <p
                style={{
                  fontSize: 12,
                  color: "#93c5fd",
                  margin: "0 0 12px",
                  lineHeight: 1.5,
                }}
              >
                Review the proposed changes, then click Apply. Manually-added
                codes are never removed.
              </p>
              {hsnPreview.diff?.new_codes?.length > 0 && (
                <div style={{ marginBottom: 12 }}>
                  <div
                    style={{
                      fontSize: 11,
                      fontWeight: 600,
                      color: "#34d399",
                      marginBottom: 6,
                    }}
                  >
                    + {hsnPreview.diff.new_codes.length} new code
                    {hsnPreview.diff.new_codes.length !== 1 ? "s" : ""} to add
                  </div>
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                    {[
                      ...hsnPreview.expected_codes,
                      ...hsnPreview.ambiguous_codes,
                    ]
                      .filter((c) => hsnPreview.diff.new_codes.includes(c.code))
                      .map((c) => (
                        <span
                          key={c.code}
                          title={
                            c.description + (c.reason ? `\n⚠ ${c.reason}` : "")
                          }
                          style={{
                            fontFamily: "monospace",
                            fontSize: 11,
                            borderRadius: 6,
                            padding: "3px 8px",
                            background: hsnPreview.ambiguous_codes.some(
                              (a) => a.code === c.code,
                            )
                              ? "rgba(245, 158, 11, 0.15)"
                              : "rgba(16, 185, 129, 0.15)",
                            color: hsnPreview.ambiguous_codes.some(
                              (a) => a.code === c.code,
                            )
                              ? "#fbbf24"
                              : "#34d399",
                            border: `1px solid ${hsnPreview.ambiguous_codes.some((a) => a.code === c.code) ? "rgba(245, 158, 11, 0.3)" : "rgba(16, 185, 129, 0.3)"}`,
                          }}
                        >
                          {c.code}
                          {hsnPreview.ambiguous_codes.some(
                            (a) => a.code === c.code,
                          ) && " ?"}
                        </span>
                      ))}
                  </div>
                </div>
              )}
              {hsnPreview.diff?.codes_no_longer_suggested?.length > 0 && (
                <div style={{ marginBottom: 12 }}>
                  <div
                    style={{
                      fontSize: 11,
                      fontWeight: 600,
                      color: "#f43f5e",
                      marginBottom: 6,
                    }}
                  >
                    Codes no longer suggested (tick to remove):
                  </div>
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
                    {hsnPreview.diff.codes_no_longer_suggested.map((code) => (
                      <label
                        key={code}
                        style={{
                          display: "flex",
                          alignItems: "center",
                          gap: 6,
                          fontSize: 12,
                          cursor: "pointer",
                          color: "#f8fafc",
                        }}
                      >
                        <input
                          type="checkbox"
                          checked={removalSet.has(code)}
                          onChange={(e) => {
                            const next = new Set(removalSet);
                            e.target.checked
                              ? next.add(code)
                              : next.delete(code);
                            setRemovalSet(next);
                          }}
                          style={{ accentColor: "#6366f1" }}
                        />
                        <span
                          style={{
                            fontFamily: "monospace",
                            fontSize: 11,
                            background: "rgba(244, 63, 94, 0.15)",
                            color: "#f43f5e",
                            borderRadius: 6,
                            padding: "2px 7px",
                            border: "1px solid rgba(244, 63, 94, 0.3)",
                          }}
                        >
                          {code}
                        </span>
                      </label>
                    ))}
                  </div>
                </div>
              )}
              <div style={{ display: "flex", gap: 8, marginTop: 14 }}>
                <button
                  onClick={handleApplyHsn}
                  disabled={hsnApplying}
                  style={s.primaryBtn}
                >
                  {hsnApplying ? "Saving…" : "Apply & save"}
                </button>
                <button
                  onClick={() => {
                    setHsnPreview(null);
                    setRemovalSet(new Set());
                  }}
                  style={s.secondaryBtn}
                >
                  Discard preview
                </button>
              </div>
            </div>
          )}

          {hsnProfile?.has_profile && !hsnPreview && (
            <div style={{ marginTop: 16 }}>
              {hsnProfile.expected_hsn_codes?.length > 0 && (
                <div style={{ marginBottom: 14 }}>
                  <div
                    style={{
                      fontSize: 11,
                      fontWeight: 600,
                      color: "#34d399",
                      marginBottom: 6,
                    }}
                  >
                    Expected HSN/SAC codes (
                    {hsnProfile.expected_hsn_codes.length})
                  </div>
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                    {hsnProfile.expected_hsn_codes.map((item) => (
                      <div
                        key={item.code}
                        title={item.description}
                        style={{
                          display: "flex",
                          alignItems: "center",
                          gap: 6,
                          fontFamily: "monospace",
                          fontSize: 11,
                          background: "rgba(16, 185, 129, 0.1)",
                          color: "#34d399",
                          borderRadius: 6,
                          padding: "3px 6px 3px 9px",
                          border: "1px solid rgba(16, 185, 129, 0.25)",
                        }}
                      >
                        {item.code}
                        {item.source === "manual" && (
                          <span
                            title="Manually added"
                            style={{
                              fontSize: 9,
                              opacity: 0.8,
                              marginLeft: 2,
                              color: "#6ee7b7",
                            }}
                          >
                            M
                          </span>
                        )}
                        <button
                          onClick={() => handleRemoveCode(item.code)}
                          disabled={removingCode === item.code}
                          style={{
                            background: "none",
                            border: "none",
                            cursor: "pointer",
                            padding: "0 2px",
                            color: "#34d399",
                            fontSize: 14,
                            lineHeight: 1,
                            opacity: 0.8,
                            display: "flex",
                            alignItems: "center",
                          }}
                        >
                          {removingCode === item.code ? "…" : "×"}
                        </button>
                      </div>
                    ))}
                  </div>
                </div>
              )}
              {hsnProfile.ambiguous_hsn_codes?.length > 0 && (
                <div style={{ marginBottom: 14 }}>
                  <div
                    style={{
                      fontSize: 11,
                      fontWeight: 600,
                      color: "#fbbf24",
                      marginBottom: 6,
                    }}
                  >
                    Watch — classify on first use (
                    {hsnProfile.ambiguous_hsn_codes.length})
                  </div>
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                    {hsnProfile.ambiguous_hsn_codes.map((item) => (
                      <div
                        key={item.code}
                        title={
                          item.description +
                          (item.reason ? `\n${item.reason}` : "")
                        }
                        style={{
                          display: "flex",
                          alignItems: "center",
                          gap: 6,
                          fontFamily: "monospace",
                          fontSize: 11,
                          background: "rgba(245, 158, 11, 0.1)",
                          color: "#fbbf24",
                          borderRadius: 6,
                          padding: "3px 6px 3px 9px",
                          border: "1px solid rgba(245, 158, 11, 0.25)",
                        }}
                      >
                        {item.code}
                        {item.source === "manual" && (
                          <span
                            title="Manually added"
                            style={{
                              fontSize: 9,
                              opacity: 0.8,
                              marginLeft: 2,
                              color: "#fde047",
                            }}
                          >
                            M
                          </span>
                        )}
                        <button
                          onClick={() => handleRemoveCode(item.code)}
                          disabled={removingCode === item.code}
                          style={{
                            background: "none",
                            border: "none",
                            cursor: "pointer",
                            padding: "0 2px",
                            color: "#fbbf24",
                            fontSize: 14,
                            lineHeight: 1,
                            opacity: 0.8,
                            display: "flex",
                            alignItems: "center",
                          }}
                        >
                          {removingCode === item.code ? "…" : "×"}
                        </button>
                      </div>
                    ))}
                  </div>
                </div>
              )}
              <div
                style={{
                  marginTop: 12,
                  padding: "14px 16px",
                  background: "#020617",
                  border: "1px solid #1e293b",
                  borderRadius: 8,
                }}
              >
                <div
                  style={{
                    fontSize: 11,
                    fontWeight: 600,
                    color: "#94a3b8",
                    marginBottom: 8,
                    textTransform: "uppercase",
                    letterSpacing: "0.04em",
                  }}
                >
                  Add a code manually
                </div>
                <div
                  style={{
                    display: "flex",
                    gap: 8,
                    alignItems: "center",
                    flexWrap: "wrap",
                  }}
                >
                  <input
                    type="text"
                    placeholder="HSN/SAC code"
                    value={manualCode}
                    onChange={(e) => setManualCode(e.target.value)}
                    style={{
                      ...s.input,
                      width: 120,
                      flex: "none",
                      fontFamily: "monospace",
                    }}
                  />
                  <select
                    value={manualCodeType}
                    onChange={(e) => setManualCodeType(e.target.value)}
                    style={{
                      ...s.input,
                      width: 80,
                      flex: "none",
                      cursor: "pointer",
                    }}
                  >
                    <option value="HSN" style={{ background: "#090d16" }}>
                      HSN
                    </option>
                    <option value="SAC" style={{ background: "#090d16" }}>
                      SAC
                    </option>
                  </select>
                  <input
                    type="text"
                    placeholder="Description (optional)"
                    value={manualDesc}
                    onChange={(e) => setManualDesc(e.target.value)}
                    style={{ ...s.input, flex: 1, minWidth: 140 }}
                  />
                  <button
                    onClick={handleAddManualCode}
                    disabled={manualAdding || !manualCode.trim()}
                    style={s.primaryBtn}
                  >
                    {manualAdding ? "Adding…" : "Add"}
                  </button>
                </div>
                <p
                  style={{ fontSize: 11, color: "#94a3b8", margin: "8px 0 0" }}
                >
                  Manually-added codes (marked M) are never removed by
                  regeneration.
                </p>
              </div>
            </div>
          )}

          {!hsnProfile?.has_profile && !hsnPreview && bizDescSaved && (
            <p style={{ fontSize: 12, color: "#94a3b8", marginTop: 10 }}>
              No profile yet — click "Generate HSN profile" above.
            </p>
          )}

          {hsnMessage && (
            <div
              style={{
                ...(hsnMessage.type === "ok" ? s.msgOk : s.msgErr),
                marginTop: 12,
              }}
            >
              {hsnMessage.text}
            </div>
          )}
        </div>

        {/* ── How to find folder ID ─────────────────────────────────────── */}
        <div style={s.section}>
          <div style={s.sectionTitle}>How to share a folder</div>
          <ol style={s.steps}>
            <li>In Google Drive, right-click a folder → Share.</li>
            <li>
              Add the service account as a Viewer:{" "}
              <code style={s.code}>
                your-service-account@project.iam.gserviceaccount.com
              </code>{" "}
              (check <code style={s.code}>gdrive_key.json → client_email</code>
              ).
            </li>
            <li>Copy the folder URL — the ID is the last segment.</li>
            <li>
              Paste it in the relevant section above and click Save, then Sync
              now.
            </li>
          </ol>
        </div>

        {/* ── Issue 12: Danger Zone — delete organisation ────────────────── */}
        <div
          style={{
            ...s.section,
            borderBottom: "none",
            borderTop: "2px solid rgba(244, 63, 94, 0.2)",
            paddingTop: 28,
            marginTop: 8,
          }}
        >
          <div style={{ ...s.sectionTitle, color: "#f43f5e" }}>Danger Zone</div>
          <p style={{ ...s.hint, color: "#94a3b8" }}>
            Permanently deletes this organisation and all its data — invoices,
            POs, waybills, GRNs, exceptions, and BigQuery rows. This cannot be
            undone.
          </p>
          <p
            style={{
              ...s.hint,
              fontSize: 12,
              color: "#64748b",
              marginBottom: 12,
            }}
          >
            Type{" "}
            <strong style={{ color: "#f8fafc" }}>{organization?.name}</strong>{" "}
            to confirm.
          </p>
          <div
            style={{
              display: "flex",
              gap: 10,
              alignItems: "center",
              flexWrap: "wrap",
            }}
          >
            <input
              type="text"
              placeholder={`Type "${organization?.name}" to confirm`}
              value={deleteOrgName}
              onChange={(e) => setDeleteOrgName(e.target.value)}
              style={{
                ...s.input,
                maxWidth: 280,
                borderColor: "rgba(244, 63, 94, 0.3)",
              }}
            />
            <button
              disabled={deletingOrg || deleteOrgName !== organization?.name}
              onClick={handleDeleteOrg}
              style={{
                background: "#f43f5e",
                color: "#fff",
                border: "none",
                borderRadius: 8,
                padding: "8px 18px",
                fontSize: 13,
                fontWeight: 600,
                cursor: "pointer",
                fontFamily: "inherit",
                whiteSpace: "nowrap",
                opacity: deleteOrgName !== organization?.name ? 0.4 : 1,
                boxShadow: "0 4px 12px rgba(244, 63, 94, 0.3)",
              }}
            >
              {deletingOrg ? "Deleting…" : "Delete organisation"}
            </button>
          </div>
          {deleteOrgMsg && (
            <div style={{ ...s.msgErr, marginTop: 12 }}>{deleteOrgMsg}</div>
          )}
        </div>
      </div>
    </div>
  );
}

const s = {
  root: {
    flex: 1,
    overflow: "auto",
    background: "#020617",
    padding: "32px 24px",
    fontFamily: "Inter, system-ui, -apple-system, sans-serif",
    fontSize: 13,
    color: "#f8fafc",
  },
  card: {
    background: "#090d16",
    border: "1px solid #1e293b",
    borderRadius: 12,
    maxWidth: 720,
    padding: "32px",
    boxShadow: "0 20px 25px -5px rgba(0, 0, 0, 0.5)",
  },
  heading: {
    margin: "0 0 24px",
    fontSize: 20,
    fontWeight: 700,
    color: "#ffffff",
    letterSpacing: "-0.025em",
  },
  section: {
    marginBottom: 32,
    paddingBottom: 32,
    borderBottom: "1px solid #1e293b",
  },
  sectionTitle: {
    fontWeight: 600,
    fontSize: 12,
    textTransform: "uppercase",
    letterSpacing: "0.05em",
    color: "#94a3b8",
    marginBottom: 8,
  },
  hint: { margin: "0 0 16px", color: "#cbd5e1", lineHeight: 1.6, fontSize: 13 },
  code: {
    background: "#1e293b",
    borderRadius: 4,
    padding: "2px 6px",
    fontFamily: "monospace",
    fontSize: 12,
    color: "#f8fafc",
  },
  folderBlock: {
    marginBottom: 20,
    paddingBottom: 20,
    borderBottom: "1px solid rgba(30, 41, 59, 0.5)",
  },
  folderLabel: {
    fontWeight: 600,
    fontSize: 13,
    color: "#f8fafc",
    marginBottom: 2,
  },
  currentFolder: {
    display: "flex",
    alignItems: "center",
    gap: 10,
    marginBottom: 12,
    padding: "8px 12px",
    background: "rgba(16, 185, 129, 0.1)",
    border: "1px solid rgba(16, 185, 129, 0.25)",
    borderRadius: 8,
  },
  currentLabel: {
    fontSize: 11,
    fontWeight: 600,
    color: "#34d399",
    textTransform: "uppercase",
    letterSpacing: "0.04em",
    whiteSpace: "nowrap",
  },
  currentCode: {
    fontFamily: "monospace",
    fontSize: 12,
    color: "#f8fafc",
    wordBreak: "break-all",
  },
  inputRow: { display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" },
  input: {
    flex: 1,
    minWidth: 200,
    border: "1px solid #1e293b",
    borderRadius: 8,
    padding: "8px 12px",
    fontSize: 13,
    fontFamily: "inherit",
    outline: "none",
    background: "#020617",
    color: "#f8fafc",
  },
  primaryBtn: {
    background: "#6366f1",
    color: "#fff",
    border: "none",
    borderRadius: 8,
    padding: "8px 16px",
    fontSize: 13,
    fontWeight: 600,
    cursor: "pointer",
    fontFamily: "inherit",
    whiteSpace: "nowrap",
    boxShadow: "0 4px 12px rgba(99, 102, 241, 0.3)",
    transition: "all 0.15s ease",
  },
  secondaryBtn: {
    background: "#090d16",
    color: "#cbd5e1",
    border: "1px solid #1e293b",
    borderRadius: 8,
    padding: "8px 14px",
    fontSize: 13,
    fontWeight: 500,
    cursor: "pointer",
    fontFamily: "inherit",
    whiteSpace: "nowrap",
    transition: "all 0.15s ease",
  },
  msgOk: {
    marginTop: 10,
    padding: "8px 12px",
    background: "rgba(16, 185, 129, 0.1)",
    border: "1px solid rgba(16, 185, 129, 0.25)",
    borderRadius: 8,
    color: "#34d399",
    fontSize: 12,
    fontWeight: 500,
  },
  msgErr: {
    marginTop: 10,
    padding: "8px 12px",
    background: "rgba(244, 63, 94, 0.1)",
    border: "1px solid rgba(244, 63, 94, 0.25)",
    borderRadius: 8,
    color: "#f43f5e",
    fontSize: 12,
    fontWeight: 500,
  },
  steps: {
    margin: "8px 0 0",
    paddingLeft: 20,
    lineHeight: 2,
    color: "#cbd5e1",
  },
};
