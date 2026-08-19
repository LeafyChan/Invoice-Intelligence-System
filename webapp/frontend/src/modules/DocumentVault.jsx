import { useState, useEffect, useCallback } from "react";
import { useAuth } from "@clerk/clerk-react";

const API = import.meta.env.VITE_API_BASE || "";
const TYPES = [
  {
    key: "invoices",
    label: "Invoices",
    icon: "🧾",
    color: "#60a5fa",
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
    color: "#a78bfa",
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
    color: "#fbbf24",
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
    color: "#34d399",
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
    color: "#f43f5e",
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
const LINK_MAP = {
  invoices: {
    po_number: ["purchase_orders", "po_number"],
    invoice_number: ["waybills", "document_number"],
  },
  purchase_orders: { po_number: ["invoices", "po_number"] },
  waybills: { document_number: ["invoices", "invoice_number"] },
  grn: {
    po_number: ["invoices", "po_number"],
    waybill_number: ["waybills", "document_number"],
  },
  material_returns: {
    grn_number: ["grn", "grn_number"],
    po_number: ["invoices", "po_number"],
  },
};
function humanKey(k) {
  return k.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
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
    const hit = (allDocs[targetType] || []).find((d) => d[targetField] === v);
    if (hit) matches.push({ field: humanKey(field), targetType, value: v });
  }
  return matches;
}

const S = {
  wrap: {
    fontFamily: "'Inter',system-ui,sans-serif",
    background: "#020617",
    minHeight: "100vh",
    color: "#f8fafc",
    display: "flex",
    flexDirection: "column",
  },
  header: {
    background: "rgba(9, 13, 22, 0.75)",
    backdropFilter: "blur(12px)",
    borderBottom: "1px solid #1e293b",
    color: "#fff",
    padding: "20px 24px",
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    flexShrink: 0,
    position: "sticky",
    top: 0,
    zIndex: 30,
  },
  btn: {
    border: "none",
    borderRadius: 8,
    padding: "7px 14px",
    fontSize: 13,
    fontWeight: 600,
    cursor: "pointer",
    fontFamily: "inherit",
    transition: "all 0.15s ease",
  },
  ghost: {
    background: "#090d16",
    border: "1px solid #1e293b",
    color: "#cbd5e1",
  },
  mono: { fontFamily: "'JetBrains Mono','Fira Code',monospace" },
};

function LinkToast({ matches, onDismiss }) {
  if (!matches.length) return null;
  return (
    <div
      style={{
        position: "fixed",
        bottom: 24,
        right: 24,
        zIndex: 600,
        background: "#090d16",
        border: "1px solid rgba(99, 102, 241, 0.4)",
        borderRadius: 12,
        boxShadow: "0 20px 25px -5px rgba(0,0,0,0.8)",
        padding: "16px",
        maxWidth: 320,
      }}
    >
      <div
        style={{
          fontWeight: 700,
          fontSize: 13,
          color: "#818cf8",
          marginBottom: 8,
        }}
      >
        🔗 Link match found
      </div>
      {matches.map((m, i) => (
        <div
          key={i}
          style={{
            fontSize: 12,
            color: "#cbd5e1",
            marginBottom: 6,
            padding: "4px 0",
            borderTop: i ? "1px solid #1e293b" : "none",
          }}
        >
          <strong>{m.field}</strong> → matches existing{" "}
          <em>{m.targetType.replace(/_/g, " ")}</em>{" "}
          <code
            style={{
              background: "#1e293b",
              padding: "2px 6px",
              borderRadius: 4,
              color: "#f8fafc",
            }}
          >
            {m.value}
          </code>
        </div>
      ))}
      <div style={{ fontSize: 11, color: "#94a3b8", margin: "8px 0 12px" }}>
        These fields link to existing scanned documents. Save to confirm.
      </div>
      <button
        onClick={onDismiss}
        style={{
          ...S.btn,
          background: "rgba(99, 102, 241, 0.15)",
          color: "#818cf8",
          border: "1px solid rgba(99, 102, 241, 0.3)",
          width: "100%",
          padding: "6px",
        }}
      >
        Dismiss
      </button>
    </div>
  );
}

function EditDrawer({ doc, typeCfg, allDocs, token, onClose, onSaved }) {
  const [vals, setVals] = useState(() => {
    const o = {};
    typeCfg.editFields.forEach((f) => {
      o[f] = doc[f] ?? "";
    });
    return o;
  });
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState(null);
  const [linkMatches, setLinkMatches] = useState([]);
  useEffect(() => {
    setLinkMatches(checkLinks(typeCfg.key, vals, allDocs));
  }, [vals]);

  async function save() {
    setSaving(true);
    setMsg(null);
    try {
      const id = doc[typeCfg.idField];
      const cleaned = {};
      typeCfg.editFields.forEach((f) => {
        cleaned[f] = vals[f] || null;
      });
      const res = await fetch(`${API}${typeCfg.patchEndpoint(id)}`, {
        method: "PATCH",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: typeCfg.patchBody(cleaned),
      });
      if (res.ok) {
        setMsg("✓ Saved");
        setTimeout(() => {
          onSaved();
          onClose();
        }, 700);
      } else {
        const e = await res.json().catch(() => ({}));
        setMsg("Error: " + (e.detail || res.status));
      }
    } catch (e) {
      setMsg("Error: " + e.message);
    } finally {
      setSaving(false);
    }
  }

  const docNum =
    doc[typeCfg.numField] || doc[typeCfg.idField]?.slice(0, 8) + "…";

  return (
    <>
      <div
        onClick={onClose}
        style={{
          position: "fixed",
          inset: 0,
          background: "rgba(0,0,0,0.7)",
          backdropFilter: "blur(4px)",
          zIndex: 400,
        }}
      />
      <div
        style={{
          position: "fixed",
          top: 0,
          right: 0,
          bottom: 0,
          width: 380,
          zIndex: 401,
          background: "#090d16",
          boxShadow: "-10px 0 25px -5px rgba(0,0,0,0.8)",
          borderLeft: "1px solid #1e293b",
          display: "flex",
          flexDirection: "column",
          overflow: "hidden",
        }}
      >
        {/* Header */}
        <div
          style={{
            padding: "16px 20px",
            background: "rgba(9, 13, 22, 0.8)",
            borderBottom: "1px solid #1e293b",
            color: "#fff",
            flexShrink: 0,
            display: "flex",
            justifyContent: "space-between",
            alignItems: "flex-start",
          }}
        >
          <div>
            <div style={{ fontWeight: 700, fontSize: 14, color: "#f8fafc" }}>
              Edit {typeCfg.label}
            </div>
            <div
              style={{
                fontSize: 11,
                color: "#94a3b8",
                marginTop: 2,
                ...S.mono,
              }}
            >
              {docNum}
            </div>
          </div>
          <button
            onClick={onClose}
            style={{
              background: "#1e293b",
              border: "none",
              borderRadius: 6,
              width: 28,
              height: 28,
              color: "#cbd5e1",
              fontSize: 16,
              cursor: "pointer",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
            }}
          >
            ×
          </button>
        </div>

        {/* Fields */}
        <div style={{ flex: 1, overflowY: "auto", padding: 20 }}>
          {typeCfg.editFields.map((f) => (
            <div key={f} style={{ marginBottom: 14 }}>
              <label
                style={{
                  fontSize: 11,
                  fontWeight: 600,
                  color: "#94a3b8",
                  display: "block",
                  marginBottom: 4,
                  textTransform: "uppercase",
                  letterSpacing: "0.03em",
                }}
              >
                {humanKey(f)}
              </label>
              <input
                value={vals[f] || ""}
                onChange={(e) =>
                  setVals((p) => ({ ...p, [f]: e.target.value }))
                }
                style={{
                  width: "100%",
                  boxSizing: "border-box",
                  background: "#020617",
                  border: "1px solid #1e293b",
                  borderRadius: 8,
                  padding: "8px 12px",
                  fontSize: 13,
                  fontFamily: "inherit",
                  outline: "none",
                  color: "#f8fafc",
                }}
              />
            </div>
          ))}

          {msg && (
            <div
              style={{
                fontSize: 12,
                padding: "8px 12px",
                borderRadius: 8,
                marginTop: 8,
                background: msg.startsWith("✓")
                  ? "rgba(16, 185, 129, 0.1)"
                  : "rgba(244, 63, 94, 0.1)",
                border: `1px solid ${msg.startsWith("✓") ? "rgba(16, 185, 129, 0.3)" : "rgba(244, 63, 94, 0.3)"}`,
                color: msg.startsWith("✓") ? "#34d399" : "#f43f5e",
              }}
            >
              {msg}
            </div>
          )}
        </div>

        {/* Footer */}
        <div
          style={{
            padding: "16px 20px",
            borderTop: "1px solid #1e293b",
            background: "rgba(9, 13, 22, 0.8)",
            display: "flex",
            gap: 10,
            flexShrink: 0,
          }}
        >
          <button
            onClick={save}
            disabled={saving}
            style={{
              ...S.btn,
              flex: 1,
              background: "#6366f1",
              color: "#fff",
              padding: "10px",
              boxShadow: "0 4px 12px rgba(99, 102, 241, 0.3)",
            }}
          >
            {saving ? "Saving…" : "Save changes"}
          </button>
          <button
            onClick={onClose}
            style={{ ...S.btn, ...S.ghost, flex: 1, padding: "10px" }}
          >
            Cancel
          </button>
        </div>
      </div>

      <LinkToast matches={linkMatches} onDismiss={() => setLinkMatches([])} />
    </>
  );
}

function DocRow({ doc, typeCfg, allDocs, token, onRefresh }) {
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(false);
  const numVal = doc[typeCfg.numField];
  const links = LINK_MAP[typeCfg.key] || {};
  const linkEntries = Object.entries(links);
  const linkedCount = linkEntries.filter(([field, linkDef]) => {
    const v = doc[field];
    if (!v) return false;
    const [targetType, targetField] = linkDef;
    return (allDocs[targetType] || []).some((d) => d[targetField] === v);
  }).length;

  const linkColor =
    linkedCount === linkEntries.length && linkEntries.length > 0
      ? {
          bg: "rgba(16, 185, 129, 0.1)",
          color: "#34d399",
          border: "rgba(16, 185, 129, 0.3)",
        }
      : linkedCount > 0
        ? {
            bg: "rgba(245, 158, 11, 0.1)",
            color: "#fbbf24",
            border: "rgba(245, 158, 11, 0.3)",
          }
        : linkEntries.length === 0
          ? {
              bg: "rgba(100, 116, 139, 0.1)",
              color: "#94a3b8",
              border: "rgba(100, 116, 139, 0.2)",
            }
          : {
              bg: "rgba(244, 63, 94, 0.1)",
              color: "#f43f5e",
              border: "rgba(244, 63, 94, 0.3)",
            };
  const SKIP = new Set([
    "org_id",
    "drive_file_id",
    "storage_path",
    "raw_data",
    "line_items",
  ]);
  const visibleEntries = Object.entries(doc)
    .filter(([k]) => !SKIP.has(k) && !k.endsWith("_id"))
    .slice(0, 18);

  return (
    <>
      <div
        onClick={() => setOpen((o) => !o)}
        style={{
          display: "flex",
          alignItems: "center",
          gap: 10,
          padding: "10px 16px",
          cursor: "pointer",
          userSelect: "none",
          borderBottom: "1px solid rgba(30, 41, 59, 0.5)",
          background: open ? "#0f172a" : "transparent",
          transition: "background 0.15s ease",
        }}
        onMouseEnter={(e) => {
          if (!open) e.currentTarget.style.background = "rgba(15, 23, 42, 0.5)";
        }}
        onMouseLeave={(e) => {
          e.currentTarget.style.background = open ? "#0f172a" : "transparent";
        }}
      >
        <span
          style={{ fontSize: 11, color: "#64748b", width: 12, flexShrink: 0 }}
        >
          {open ? "▾" : "▸"}
        </span>
        <span style={{ fontSize: 13, flexShrink: 0 }}>{typeCfg.icon}</span>
        <span
          style={{
            fontSize: 12,
            fontWeight: 500,
            flex: 1,
            color: "#f8fafc",
            ...S.mono,
          }}
        >
          {numVal || (
            <span
              style={{
                color: "#64748b",
                fontStyle: "italic",
                fontFamily: "inherit",
              }}
            >
              no number extracted
            </span>
          )}
        </span>

        {doc.file_name && (
          <span
            style={{
              fontSize: 10,
              color: "#94a3b8",
              maxWidth: 160,
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
            }}
          >
            {doc.file_name}
          </span>
        )}
        {linkEntries.length > 0 && (
          <span
            style={{
              fontSize: 10,
              fontWeight: 600,
              padding: "2px 8px",
              borderRadius: "9999px",
              background: linkColor.bg,
              color: linkColor.color,
              border: `1px solid ${linkColor.border}`,
              whiteSpace: "nowrap",
            }}
          >
            {linkedCount}/{linkEntries.length} linked
          </span>
        )}
        <button
          onClick={(e) => {
            e.stopPropagation();
            setEditing(true);
          }}
          title="Edit"
          style={{
            background: "#1e293b",
            border: "1px solid #334155",
            cursor: "pointer",
            fontSize: 12,
            color: "#cbd5e1",
            padding: "3px 6px",
            borderRadius: 6,
            lineHeight: 1,
          }}
        >
          ✏️
        </button>
      </div>

      {open && (
        <div
          style={{
            padding: "12px 16px 14px 42px",
            background: "#060913",
            borderBottom: "1px solid #1e293b",
          }}
        >
          {/* Fields grid */}
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "1fr 1fr",
              gap: "6px 24px",
              marginBottom: 12,
            }}
          >
            {visibleEntries.map(([k, v]) => {
              const fmtd = fmt(v);
              if (fmtd === null) return null;
              return (
                <div key={k} style={{ fontSize: 11 }}>
                  <span style={{ color: "#64748b" }}>{humanKey(k)}: </span>
                  <span style={{ color: "#cbd5e1", fontWeight: 500 }}>
                    {fmtd}
                  </span>
                </div>
              );
            })}
          </div>

          {/* Link status rows */}
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            {linkEntries.map(([field, linkDef]) => {
              const [targetType, targetField] = linkDef;
              const v = doc[field];

              const hit =
                v &&
                (allDocs[targetType] || []).find((d) => d[targetField] === v);
              return (
                <div
                  key={field}
                  style={{
                    fontSize: 11,
                    padding: "4px 10px",
                    borderRadius: 6,
                    background: hit
                      ? "rgba(16, 185, 129, 0.1)"
                      : v
                        ? "rgba(244, 63, 94, 0.1)"
                        : "#0f172a",
                    color: hit ? "#34d399" : v ? "#f43f5e" : "#64748b",
                    border: `1px solid ${hit ? "rgba(16, 185, 129, 0.2)" : v ? "rgba(244, 63, 94, 0.2)" : "#1e293b"}`,
                  }}
                >
                  {humanKey(field)}
                  {v ? ` = ${v}` : " (empty)"} → {typeCfg.label}:{" "}
                  {hit ? "✓ matched" : v ? "✗ no match in scanned docs" : "—"}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {editing && (
        <EditDrawer
          doc={doc}
          typeCfg={typeCfg}
          allDocs={allDocs}
          token={token}
          onClose={() => setEditing(false)}
          onSaved={onRefresh}
        />
      )}
    </>
  );
}

function Folder({ typeCfg, allDocs, token, onRefresh }) {
  const docs = allDocs[typeCfg.key] || [];
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");

  const filtered = search
    ? docs.filter((d) => {
        const num = String(d[typeCfg.numField] || "").toLowerCase();
        const name = String(d.file_name || "").toLowerCase();
        const q = search.toLowerCase();
        return num.includes(q) || name.includes(q);
      })
    : docs;
  const links = LINK_MAP[typeCfg.key] || {};
  const linkCount = Object.keys(links).length;
  const fullyLinked =
    linkCount === 0
      ? docs.length
      : docs.filter((doc) =>
          Object.entries(links).every(([field, linkDef]) => {
            const v = doc[field];
            if (!v) return false;
            const [targetType, targetField] = linkDef;
            return (allDocs[targetType] || []).some(
              (d) => d[targetField] === v,
            );
          }),
        ).length;

  return (
    <div
      style={{
        marginBottom: 8,
        background: "#090d16",
        border: "1px solid #1e293b",
        borderRadius: 12,
        overflow: "hidden",
      }}
    >
      <div
        onClick={() => setOpen((o) => !o)}
        style={{
          display: "flex",
          alignItems: "center",
          gap: 12,
          padding: "12px 16px",
          cursor: "pointer",
          userSelect: "none",
          background: open
            ? "rgba(99, 102, 241, 0.05)"
            : "rgba(9, 13, 22, 0.8)",
          borderLeft: `4px solid ${typeCfg.color}`,
          transition: "background 0.15s",
        }}
      >
        <span style={{ fontSize: 16, lineHeight: 1 }}>
          {open ? "📂" : "📁"}
        </span>
        <span
          style={{ fontWeight: 600, fontSize: 13, color: "#f8fafc", flex: 1 }}
        >
          {typeCfg.icon} {typeCfg.label}
        </span>

        {docs.length > 0 && linkCount > 0 && (
          <span
            style={{
              fontSize: 10,
              padding: "2px 8px",
              borderRadius: "9999px",
              fontWeight: 600,
              background:
                fullyLinked === docs.length
                  ? "rgba(16, 185, 129, 0.1)"
                  : "rgba(245, 158, 11, 0.1)",
              color: fullyLinked === docs.length ? "#34d399" : "#fbbf24",
              border: `1px solid ${fullyLinked === docs.length ? "rgba(16, 185, 129, 0.3)" : "rgba(245, 158, 11, 0.3)"}`,
            }}
          >
            {fullyLinked}/{docs.length} linked
          </span>
        )}
        <span
          style={{
            fontSize: 11,
            fontWeight: 700,
            background: "rgba(255, 255, 255, 0.08)",
            color: "#f8fafc",
            borderRadius: "9999px",
            padding: "2px 10px",
            border: "1px solid rgba(255, 255, 255, 0.1)",
          }}
        >
          {docs.length}
        </span>
        <span style={{ fontSize: 11, color: "#64748b" }}>
          {open ? "▲" : "▼"}
        </span>
      </div>

      {open && (
        <div style={{ borderTop: "1px solid #1e293b" }}>
          {docs.length > 7 && (
            <div
              style={{
                padding: "8px 16px",
                background: "#020617",
                borderBottom: "1px solid #1e293b",
              }}
            >
              <input
                placeholder={`Search ${typeCfg.label.toLowerCase()}…`}
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                onClick={(e) => e.stopPropagation()}
                style={{
                  width: "100%",
                  boxSizing: "border-box",
                  background: "#090d16",
                  border: "1px solid #1e293b",
                  borderRadius: 8,
                  padding: "7px 12px",
                  fontSize: 12,
                  fontFamily: "inherit",
                  outline: "none",
                  color: "#f8fafc",
                }}
              />
            </div>
          )}

          {filtered.length === 0 ? (
            <div
              style={{
                padding: "16px 36px",
                fontSize: 12,
                color: "#64748b",
                fontStyle: "italic",
              }}
            >
              {docs.length === 0
                ? "No documents synced yet — go to Settings and run a sync."
                : "No matches."}
            </div>
          ) : (
            filtered.map((doc) => (
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

export default function DocumentVault() {
  const { getToken } = useAuth();
  const [allDocs, setAllDocs] = useState({});
  const [token, setToken] = useState(null);
  const [loading, setLoading] = useState(false);
  const [lastSync, setLastSync] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const tok = await getToken({ skipCache: true });
      setToken(tok);
      const h = { Authorization: `Bearer ${tok}` };

      const results = await Promise.allSettled(
        TYPES.map((t) =>
          fetch(`${API}${t.endpoint}`, { headers: h }).then((r) =>
            r.ok ? r.json() : null,
          ),
        ),
      );

      const map = {};
      TYPES.forEach((t, i) => {
        const r = results[i];
        if (r.status === "fulfilled" && r.value) {
          const val = r.value;
          map[t.key] = t.listKey
            ? val[t.listKey] || []
            : Array.isArray(val)
              ? val
              : val.items || val.results || [];
        } else {
          map[t.key] = [];
        }
      });
      setAllDocs(map);
      setLastSync(new Date().toLocaleTimeString("en-IN"));
    } finally {
      setLoading(false);
    }
  }, [getToken]);

  useEffect(() => {
    load();
  }, [load]);

  const total = Object.values(allDocs).reduce((s, a) => s + a.length, 0);

  return (
    <div style={S.wrap}>
      {/* Header */}
      <div style={S.header}>
        <div>
          <div
            style={{
              fontWeight: 700,
              fontSize: 18,
              color: "#ffffff",
              letterSpacing: "-0.025em",
            }}
          >
            📂 Document Vault
          </div>
          <div style={{ fontSize: 12, color: "#94a3b8", marginTop: 2 }}>
            {total} files scanned{lastSync ? ` · refreshed ${lastSync}` : ""}
          </div>
        </div>
        <button
          onClick={load}
          disabled={loading}
          style={{
            ...S.btn,
            background: "#6366f1",
            color: "#fff",
            boxShadow: "0 4px 12px rgba(99, 102, 241, 0.3)",
          }}
        >
          {loading ? "Loading…" : "↻ Refresh"}
        </button>
      </div>

      {/* Summary strip */}
      <div
        style={{
          display: "flex",
          borderBottom: "1px solid #1e293b",
          background: "rgba(9, 13, 22, 0.6)",
          flexShrink: 0,
        }}
      >
        {TYPES.map((t) => (
          <div
            key={t.key}
            style={{
              flex: 1,
              padding: "14px 8px",
              textAlign: "center",
              borderRight: "1px solid #1e293b",
            }}
          >
            <div style={{ fontSize: 18, marginBottom: 2 }}>{t.icon}</div>
            <div
              style={{
                fontSize: 22,
                fontWeight: 700,
                color: t.color,
                lineHeight: 1.1,
              }}
            >
              {(allDocs[t.key] || []).length}
            </div>
            <div
              style={{
                fontSize: 11,
                color: "#94a3b8",
                marginTop: 3,
                fontWeight: 500,
              }}
            >
              {t.label}
            </div>
          </div>
        ))}
      </div>

      {/* Explorer tree */}
      <div style={{ flex: 1, overflowY: "auto", padding: "24px 16px" }}>
        <div style={{ maxWidth: 860, margin: "0 auto" }}>
          {TYPES.map((t) => (
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
