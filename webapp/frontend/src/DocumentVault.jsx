// DocumentVault.jsx
// Drop-in replacement for Exceptions.jsx.
// Windows-Explorer-style tree: 5 doc-type folders, each expandable.
// Every row: click to expand data, ✏️ to edit, link-match badges.
// Edit drawer: saves via PATCH for all 5 doc types.
// Link suggestion popup: fires when an edited ref field matches an existing doc.

import { useState, useEffect, useCallback } from "react";
import { useAuth } from "@clerk/clerk-react";

const API = import.meta.env.VITE_API_BASE || "";

// ── Config ────────────────────────────────────────────────────────────────────

const TYPES = [
  {
    key: "invoices",
    label: "Invoices",
    icon: "🧾",
    color: "#3B82F6",
    endpoint: "/vault/invoices?limit=200",
    listKey: "items",
    idField: "invoice_id",
    numField: "invoice_number",
    patchEndpoint: (id) => `/invoices/${id}`,
    patchBody: (fields) => JSON.stringify({ fields, line_items: [] }),
    editFields: [
      "vendor_name",
      "vendor_gstin",
      "invoice_number",
      "invoice_date",
      "po_number",
      "total_amount",
      "payment_terms",
    ],
  },
  {
    key: "purchase_orders",
    label: "Purchase Orders",
    icon: "📋",
    color: "#8B5CF6",
    endpoint: "/vault/purchase-orders?limit=200",
    listKey: "items",
    idField: "po_id",
    numField: "po_number",
    patchEndpoint: (id) => `/purchase-orders/${id}`,
    patchBody: (fields) => JSON.stringify(fields),
    editFields: [
      "po_number",
      "po_date",
      "vendor_name",
      "vendor_gstin",
      "total_amount",
      "incoterm",
      "incoterm_raw",
      "requested_transport_mode",
      "delivery_date_requested",
    ],
  },
  {
    key: "waybills",
    label: "E-Waybills",
    icon: "🚛",
    color: "#F59E0B",
    endpoint: "/vault/waybills?limit=200",
    listKey: "items",
    idField: "waybill_id",
    numField: "document_number",
    patchEndpoint: (id) => `/waybills/${id}`,
    patchBody: (fields) => JSON.stringify(fields),
    editFields: [
      "ewb_number",
      "ewb_date",
      "ewb_valid_until",
      "document_number",
      "transport_mode_label",
      "vehicle_number",
      "supplier_name",
      "recipient_name",
    ],
  },
  {
    key: "grn",
    label: "GRN",
    icon: "📦",
    color: "#10B981",
    endpoint: "/vault/grn?limit=200",
    listKey: "items",
    idField: "grn_id",
    numField: "grn_number",
    patchEndpoint: (id) => `/grn/${id}`,
    patchBody: (fields) => JSON.stringify(fields),
    editFields: [
      "grn_number",
      "grn_date",
      "po_number",
      "waybill_number",
      "vendor_name",
      "total_quantity_ordered",
      "total_quantity_received",
    ],
  },
  {
    key: "material_returns",
    label: "Material Returns",
    icon: "↩️",
    color: "#EF4444",
    endpoint: "/vault/material-returns?limit=200",
    listKey: "items",
    idField: "mrn_id",
    numField: "mrn_number",
    patchEndpoint: (id) => `/material-returns/${id}`,
    patchBody: (fields) => JSON.stringify(fields),
    editFields: [
      "mrn_number",
      "mrn_date",
      "grn_number",
      "po_number",
      "vendor_name",
      "return_reason",
      "total_quantity_returned",
    ],
  },
];

// Which ref fields on each type should match against which other type's numField
const LINK_MAP = {
  invoices:        { po_number: ["purchase_orders","po_number"], invoice_number: ["waybills","document_number"] },
  purchase_orders: { po_number: ["invoices","po_number"] },
  waybills:        { document_number: ["invoices","invoice_number"] },
  grn:             { po_number: ["invoices","po_number"], waybill_number: ["waybills","document_number"] },
  material_returns:{ grn_number: ["grn","grn_number"], po_number: ["invoices","po_number"] },
};

// ── Helpers ───────────────────────────────────────────────────────────────────

function humanKey(k) {
  return k.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
}

function fmt(v) {
  if (v == null) return null;
  if (typeof v === "boolean") return v ? "Yes" : "No";
  const s = String(v);
  if (/^\d{4}-\d{2}-\d{2}/.test(s)) return s.slice(0, 10);
  return s.length > 80 ? s.slice(0, 80) + "…" : s;
}

function checkLinks(docType, vals, allDocs) {
  const links = LINK_MAP[docType] || {};
  const matches = [];
  for (const [field, linkDef] of Object.entries(links)) {
    const [targetType, targetField] = linkDef;
    const v = (vals[field] || "").trim();
    if (!v) continue;
    const hit = (allDocs[targetType] || []).find(d => d[targetField] === v);
    if (hit) matches.push({ field: humanKey(field), targetType, value: v });
  }
  return matches;
}

// ── Styles ────────────────────────────────────────────────────────────────────

const S = {
  wrap:   { fontFamily: "'Inter',system-ui,sans-serif", background: "#F8FAFC", minHeight: "100vh", color: "#111318", display: "flex", flexDirection: "column" },
  header: { background: "#1E3A5F", color: "#fff", padding: "14px 20px", display: "flex", alignItems: "center", justifyContent: "space-between", flexShrink: 0 },
  btn:    { border: "none", borderRadius: 6, padding: "6px 14px", fontSize: 12, fontWeight: 600, cursor: "pointer", fontFamily: "inherit" },
  ghost:  { background: "none", border: "1px solid #D1D5DB", color: "#374151" },
  mono:   { fontFamily: "'JetBrains Mono','Fira Code',monospace" },
};

// ── Link suggestion toast ─────────────────────────────────────────────────────

function LinkToast({ matches, onDismiss }) {
  if (!matches.length) return null;
  return (
    <div style={{
      position: "fixed", bottom: 24, right: 24, zIndex: 600,
      background: "#fff", border: "2px solid #3B82F6", borderRadius: 10,
      boxShadow: "0 8px 32px rgba(0,0,0,0.18)", padding: "14px 16px", maxWidth: 320,
    }}>
      <div style={{ fontWeight: 700, fontSize: 13, color: "#1E3A5F", marginBottom: 8 }}>🔗 Link match found</div>
      {matches.map((m, i) => (
        <div key={i} style={{ fontSize: 12, color: "#374151", marginBottom: 4, padding: "3px 0", borderTop: i ? "1px solid #F1F5F9" : "none" }}>
          <strong>{m.field}</strong> → matches existing <em>{m.targetType.replace(/_/g, " ")}</em> <code style={{ background: "#F1F5F9", padding: "1px 4px", borderRadius: 3 }}>{m.value}</code>
        </div>
      ))}
      <div style={{ fontSize: 11, color: "#6B7280", margin: "8px 0 10px" }}>
        These fields link to existing scanned documents. Save to confirm.
      </div>
      <button onClick={onDismiss} style={{ ...S.btn, background: "#EFF6FF", color: "#1D4ED8", border: "1px solid #BFDBFE" }}>Dismiss</button>
    </div>
  );
}

// ── Edit drawer ───────────────────────────────────────────────────────────────

function EditDrawer({ doc, typeCfg, allDocs, token, onClose, onSaved }) {
  const [vals, setVals] = useState(() => {
    const o = {};
    typeCfg.editFields.forEach(f => { o[f] = doc[f] ?? ""; });
    return o;
  });
  const [saving, setSaving] = useState(false);
  const [msg, setMsg]       = useState(null);
  const [linkMatches, setLinkMatches] = useState([]);

  // Recompute link matches on every keystroke — no extra API calls
  useEffect(() => {
    setLinkMatches(checkLinks(typeCfg.key, vals, allDocs));
  }, [vals]);

  async function save() {
    setSaving(true); setMsg(null);
    try {
      const id = doc[typeCfg.idField];
      const cleaned = {};
      typeCfg.editFields.forEach(f => { cleaned[f] = vals[f] || null; });
      const res = await fetch(`${API}${typeCfg.patchEndpoint(id)}`, {
        method: "PATCH",
        headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
        body: typeCfg.patchBody(cleaned),
      });
      if (res.ok) {
        setMsg("✓ Saved");
        setTimeout(() => { onSaved(); onClose(); }, 700);
      } else {
        const e = await res.json().catch(() => ({}));
        setMsg("Error: " + (e.detail || res.status));
      }
    } catch (e) { setMsg("Error: " + e.message); }
    finally { setSaving(false); }
  }

  const docNum = doc[typeCfg.numField] || doc[typeCfg.idField]?.slice(0, 8) + "…";

  return (
    <>
      <div onClick={onClose} style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.3)", zIndex: 400 }} />
      <div style={{
        position: "fixed", top: 0, right: 0, bottom: 0, width: 360, zIndex: 401,
        background: "#fff", boxShadow: "-4px 0 24px rgba(0,0,0,0.15)",
        display: "flex", flexDirection: "column", overflow: "hidden",
      }}>
        {/* Header */}
        <div style={{ padding: "13px 16px", background: "#1E3A5F", color: "#fff", flexShrink: 0, display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
          <div>
            <div style={{ fontWeight: 700, fontSize: 14 }}>Edit {typeCfg.label}</div>
            <div style={{ fontSize: 11, opacity: 0.7, marginTop: 2, ...S.mono }}>{docNum}</div>
          </div>
          <button onClick={onClose} style={{ background: "none", border: "none", color: "#fff", fontSize: 20, cursor: "pointer", lineHeight: 1, padding: 0 }}>×</button>
        </div>

        {/* Fields */}
        <div style={{ flex: 1, overflowY: "auto", padding: 16 }}>
          {typeCfg.editFields.map(f => (
            <div key={f} style={{ marginBottom: 11 }}>
              <label style={{ fontSize: 11, fontWeight: 600, color: "#6B7280", display: "block", marginBottom: 3 }}>
                {humanKey(f)}
              </label>
              <input
                value={vals[f] || ""}
                onChange={e => setVals(p => ({ ...p, [f]: e.target.value }))}
                style={{
                  width: "100%", boxSizing: "border-box",
                  border: "1px solid #D1D5DB", borderRadius: 5,
                  padding: "6px 8px", fontSize: 13, fontFamily: "inherit", outline: "none",
                }}
              />
            </div>
          ))}

          {msg && (
            <div style={{
              fontSize: 12, padding: "7px 10px", borderRadius: 5, marginTop: 6,
              background: msg.startsWith("✓") ? "#D1FAE5" : "#FEE2E2",
              color:      msg.startsWith("✓") ? "#065F46"  : "#991B1B",
            }}>{msg}</div>
          )}
        </div>

        {/* Footer */}
        <div style={{ padding: "12px 16px", borderTop: "1px solid #E5E7EB", display: "flex", gap: 8, flexShrink: 0 }}>
          <button onClick={save} disabled={saving} style={{ ...S.btn, flex: 1, background: "#1E3A5F", color: "#fff", padding: "9px" }}>
            {saving ? "Saving…" : "Save changes"}
          </button>
          <button onClick={onClose} style={{ ...S.btn, ...S.ghost, flex: 1, padding: "9px" }}>Cancel</button>
        </div>
      </div>

      <LinkToast matches={linkMatches} onDismiss={() => setLinkMatches([])} />
    </>
  );
}

// ── Data row (expandable) ─────────────────────────────────────────────────────

function DocRow({ doc, typeCfg, allDocs, token, onRefresh }) {
  const [open, setOpen]     = useState(false);
  const [editing, setEditing] = useState(false);

  const numVal = doc[typeCfg.numField];

  // Compute link status for badge
  const links = LINK_MAP[typeCfg.key] || {};
  const linkEntries = Object.entries(links);
  const linkedCount = linkEntries.filter(([field, linkDef]) => {
    const v = doc[field]; if (!v) return false;

    const [targetType, targetField] = linkDef;
    return (allDocs[targetType] || []).some(d => d[targetField] === v);
  }).length;

  const linkColor = linkedCount === linkEntries.length && linkEntries.length > 0
    ? { bg: "#D1FAE5", color: "#065F46" }
    : linkedCount > 0
    ? { bg: "#FEF3C7", color: "#92400E" }
    : linkEntries.length === 0
    ? { bg: "#F1F5F9", color: "#6B7280" }
    : { bg: "#FEE2E2", color: "#991B1B" };

  // Visible fields for expanded view — skip UUIDs and internal keys
  const SKIP = new Set(["org_id", "drive_file_id", "storage_path", "raw_data", "line_items"]);
  const visibleEntries = Object.entries(doc)
    .filter(([k]) => !SKIP.has(k) && !k.endsWith("_id"))
    .slice(0, 18);

  return (
    <>
      <div
        onClick={() => setOpen(o => !o)}
        style={{
          display: "flex", alignItems: "center", gap: 8,
          padding: "7px 12px", cursor: "pointer", userSelect: "none",
          borderBottom: "1px solid #F1F5F9",
          background: open ? "#F0F6FF" : "#fff",
        }}
        onMouseEnter={e => { if (!open) e.currentTarget.style.background = "#F8FAFC"; }}
        onMouseLeave={e => { e.currentTarget.style.background = open ? "#F0F6FF" : "#fff"; }}
      >
        <span style={{ fontSize: 11, color: "#9CA3AF", width: 12, flexShrink: 0 }}>{open ? "▾" : "▸"}</span>
        <span style={{ fontSize: 13, flexShrink: 0 }}>{typeCfg.icon}</span>
        <span style={{ fontSize: 12, fontWeight: 500, flex: 1, color: "#111318", ...S.mono }}>
          {numVal || <span style={{ color: "#9CA3AF", fontStyle: "italic", fontFamily: "inherit" }}>no number extracted</span>}
        </span>
        {doc.file_name && (
          <span style={{ fontSize: 10, color: "#9CA3AF", maxWidth: 160, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {doc.file_name}
          </span>
        )}
        {linkEntries.length > 0 && (
          <span style={{
            fontSize: 10, fontWeight: 600, padding: "2px 7px", borderRadius: 10,
            background: linkColor.bg, color: linkColor.color, whiteSpace: "nowrap",
          }}>
            {linkedCount}/{linkEntries.length} linked
          </span>
        )}
        <button
          onClick={e => { e.stopPropagation(); setEditing(true); }}
          title="Edit"
          style={{ background: "none", border: "none", cursor: "pointer", fontSize: 13, color: "#9CA3AF", padding: "1px 4px", borderRadius: 3, lineHeight: 1 }}
        >✏️</button>
      </div>

      {open && (
        <div style={{
          padding: "10px 12px 10px 36px", background: "#F8FAFE",
          borderBottom: "1px solid #E5E7EB",
        }}>
          {/* Fields grid */}
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "3px 20px", marginBottom: 8 }}>
            {visibleEntries.map(([k, v]) => {
              const fmtd = fmt(v);
              if (fmtd === null) return null;
              return (
                <div key={k} style={{ fontSize: 11 }}>
                  <span style={{ color: "#9CA3AF" }}>{humanKey(k)}: </span>
                  <span style={{ color: "#374151", fontWeight: 500 }}>{fmtd}</span>
                </div>
              );
            })}
          </div>

          {/* Link status rows */}
          {linkEntries.map(([field, linkDef]) => {
            const [targetType, targetField] = linkDef;
            const v = doc[field];

            const hit = v && (allDocs[targetType] || []).find(d => d[targetField] === v);
            return (
              <div key={field} style={{
                fontSize: 11, padding: "3px 8px", borderRadius: 4, marginBottom: 3,
                background: hit ? "#D1FAE5" : v ? "#FEE2E2" : "#F3F4F6",
                color:      hit ? "#065F46"  : v ? "#991B1B" : "#9CA3AF",
              }}>
                {humanKey(field)}{v ? ` = ${v}` : " (empty)"} →{" "}
                {cfg.label}: {hit ? "✓ matched" : v ? "✗ no match in scanned docs" : "—"}
              </div>
            );
          })}
        </div>
      )}

      {editing && (
        <EditDrawer
          doc={doc} typeCfg={typeCfg} allDocs={allDocs} token={token}
          onClose={() => setEditing(false)}
          onSaved={onRefresh}
        />
      )}
    </>
  );
}

// ── Folder (collapsible) ──────────────────────────────────────────────────────

function Folder({ typeCfg, allDocs, token, onRefresh }) {
  const docs = allDocs[typeCfg.key] || [];
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");

  const filtered = search
    ? docs.filter(d => {
        const num = String(d[typeCfg.numField] || "").toLowerCase();
        const name = String(d.file_name || "").toLowerCase();
        const q = search.toLowerCase();
        return num.includes(q) || name.includes(q);
      })
    : docs;

  // Folder-level link health summary
  const links = LINK_MAP[typeCfg.key] || {};
  const linkCount = Object.keys(links).length;
  const fullyLinked = linkCount === 0 ? docs.length : docs.filter(doc =>
    Object.entries(links).every(([field, linkDef]) => {
      const v = doc[field]; if (!v) return false;
      const [targetType, targetField] = linkDef;
      return (allDocs[targetType] || []).some(d => d[targetField] === v);
    })
  ).length;

  return (
    <div style={{ marginBottom: 2 }}>
      <div
        onClick={() => setOpen(o => !o)}
        style={{
          display: "flex", alignItems: "center", gap: 10,
          padding: "9px 14px", cursor: "pointer", userSelect: "none",
          background: open ? "#EFF6FF" : "#F8FAFC",
          borderLeft: `4px solid ${open ? typeCfg.color : "#E5E7EB"}`,
          borderBottom: "1px solid #E5E7EB",
          transition: "border-color 0.15s",
        }}
      >
        <span style={{ fontSize: 16, lineHeight: 1 }}>{open ? "📂" : "📁"}</span>
        <span style={{ fontWeight: 700, fontSize: 13, color: "#1E3A5F", flex: 1 }}>
          {typeCfg.icon} {typeCfg.label}
        </span>
        {docs.length > 0 && linkCount > 0 && (
          <span style={{
            fontSize: 10, padding: "2px 7px", borderRadius: 10, fontWeight: 600,
            background: fullyLinked === docs.length ? "#D1FAE5" : "#FEF3C7",
            color:      fullyLinked === docs.length ? "#065F46"  : "#92400E",
          }}>
            {fullyLinked}/{docs.length} linked
          </span>
        )}
        <span style={{
          fontSize: 11, fontWeight: 700,
          background: typeCfg.color, color: "#fff",
          borderRadius: 10, padding: "2px 9px",
        }}>{docs.length}</span>
        <span style={{ fontSize: 11, color: "#9CA3AF" }}>{open ? "▲" : "▼"}</span>
      </div>

      {open && (
        <div>
          {docs.length > 7 && (
            <div style={{ padding: "6px 14px", background: "#F1F5F9", borderBottom: "1px solid #E5E7EB" }}>
              <input
                placeholder={`Search ${typeCfg.label.toLowerCase()}…`}
                value={search}
                onChange={e => setSearch(e.target.value)}
                onClick={e => e.stopPropagation()}
                style={{
                  width: "100%", boxSizing: "border-box",
                  border: "1px solid #D1D5DB", borderRadius: 5,
                  padding: "5px 8px", fontSize: 12, fontFamily: "inherit", outline: "none",
                }}
              />
            </div>
          )}

          {filtered.length === 0 ? (
            <div style={{ padding: "12px 36px", fontSize: 12, color: "#9CA3AF", fontStyle: "italic" }}>
              {docs.length === 0 ? "No documents synced yet — go to Settings and run a sync." : "No matches."}
            </div>
          ) : (
            filtered.map(doc => (
              <DocRow
                key={doc[typeCfg.idField]}
                doc={doc}
                typeCfg={typeCfg}
                allDocs={allDocs}
                token={token}
                onRefresh={onRefresh}
              />
            ))
          )}
        </div>
      )}
    </div>
  );
}

// ── Root ──────────────────────────────────────────────────────────────────────

export default function DocumentVault() {
  const { getToken } = useAuth();
  const [allDocs, setAllDocs]   = useState({});
  const [token, setToken]       = useState(null);
  const [loading, setLoading]   = useState(false);
  const [lastSync, setLastSync] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const tok = await getToken({ skipCache: true });
      setToken(tok);
      const h = { Authorization: `Bearer ${tok}` };

      const results = await Promise.allSettled(
        TYPES.map(t => fetch(`${API}${t.endpoint}`, { headers: h }).then(r => r.ok ? r.json() : null))
      );

      const map = {};
      TYPES.forEach((t, i) => {
        const r = results[i];
        if (r.status === "fulfilled" && r.value) {
          // Invoices/POs return { invoices:[...] } / { purchase_orders:[...] }
          // Waybills/GRN/MRs return array directly
          const val = r.value;
          map[t.key] = t.listKey ? (val[t.listKey] || []) : (Array.isArray(val) ? val : (val.items || val.results || []));
        } else {
          map[t.key] = [];
        }
      });
      setAllDocs(map);
      setLastSync(new Date().toLocaleTimeString("en-IN"));
    } finally { setLoading(false); }
  }, [getToken]);

  useEffect(() => { load(); }, [load]);

  const total = Object.values(allDocs).reduce((s, a) => s + a.length, 0);

  return (
    <div style={S.wrap}>
      {/* Header */}
      <div style={S.header}>
        <div>
          <div style={{ fontWeight: 700, fontSize: 17 }}>📂 Document Vault</div>
          <div style={{ fontSize: 11, opacity: 0.7, marginTop: 2 }}>
            {total} files scanned{lastSync ? ` · refreshed ${lastSync}` : ""}
          </div>
        </div>
        <button
          onClick={load} disabled={loading}
          style={{ ...S.btn, background: loading ? "#9CA3AF" : "#fff", color: "#1E3A5F" }}
        >{loading ? "Loading…" : "↻ Refresh"}</button>
      </div>

      {/* Summary strip */}
      <div style={{ display: "flex", borderBottom: "2px solid #E5E7EB", background: "#fff", flexShrink: 0 }}>
        {TYPES.map(t => (
          <div key={t.key} style={{ flex: 1, padding: "8px 4px", textAlign: "center", borderRight: "1px solid #F1F5F9" }}>
            <div style={{ fontSize: 17 }}>{t.icon}</div>
            <div style={{ fontSize: 20, fontWeight: 700, color: t.color, lineHeight: 1.1 }}>
              {(allDocs[t.key] || []).length}
            </div>
            <div style={{ fontSize: 10, color: "#9CA3AF", marginTop: 1 }}>{t.label}</div>
          </div>
        ))}
      </div>

      {/* Explorer tree */}
      <div style={{ flex: 1, overflowY: "auto", padding: "12px" }}>
        <div style={{ maxWidth: 860, margin: "0 auto" }}>
          {TYPES.map(t => (
            <Folder
              key={t.key}
              typeCfg={t}
              allDocs={allDocs}
              token={token}
              onRefresh={load}
            />
          ))}
        </div>
      </div>
    </div>
  );
}