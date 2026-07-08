/**
 * App.jsx
 * =======
 * Top-level shell. 9 top-level tabs:
 *   Invoices / Vendors /
 *   Exceptions / ITC Summary / Analytics / Activity / Settings
 *
 *
 * S17 additions:
 *   - Vendors tab (VendorScorecard)
 *   - ErrorBoundary key reset on every tab change
 */

import { useState, Component } from "react";
import {
  SignedIn,
  SignedOut,
  SignInButton,
  UserButton,
  useAuth,
  useOrganization,
  OrganizationSwitcher,
  CreateOrganization,
} from "@clerk/clerk-react";
import InvoiceList     from "./InvoiceList";
import Settings        from "./Settings";
import ActivityLog     from "./ActivityLog";
import ItcSummary      from "./Itcsummary";
import Exceptions      from "./Exceptions";
import Analytics       from "./Analytics";
import VendorScorecard from "./VendorScorecard";

// ── Error boundary ────────────────────────────────────────────────────────────

class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }
  static getDerivedStateFromError(error) {
    return { error };
  }
  render() {
    if (this.state.error) {
      return (
        <div style={{
          flex: 1, display: "flex", alignItems: "center", justifyContent: "center",
          background: "#F7F8FA", fontFamily: "Inter, system-ui, sans-serif",
        }}>
          <div style={{
            background: "#fff", border: "1px solid #FECACA", borderRadius: 12,
            padding: "32px 36px", maxWidth: 420, textAlign: "center",
          }}>
            <div style={{ fontSize: 28, marginBottom: 12 }}>⚠</div>
            <div style={{ fontSize: 14, fontWeight: 700, color: "#B91C1C", marginBottom: 8 }}>
              This tab ran into an error
            </div>
            <div style={{ fontSize: 12, color: "#6B7280", marginBottom: 16, lineHeight: 1.6 }}>
              {String(this.state.error)}
            </div>
            <button
              onClick={() => this.setState({ error: null })}
              style={{
                background: "#312E81", color: "#fff", border: "none",
                borderRadius: 8, padding: "8px 18px", fontSize: 13,
                cursor: "pointer", fontFamily: "inherit",
              }}
            >
              Try again
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}

// ── Login page ────────────────────────────────────────────────────────────────

function LoginPage() {
  return (
    <div style={ls.root}>
      <div style={ls.panel}>
        <div style={ls.logoWrap}>
          <div style={ls.logoMark}>IIS</div>
        </div>
        <h1 style={ls.heading}>Invoice Intelligence</h1>
        <p style={ls.subheading}>
          GST-aware invoice extraction and compliance tracking for Indian SMEs.
        </p>
        <div style={{ background: "#F0F4FF", border: "1px solid #C7D2FE", borderRadius: 8, padding: "14px 16px", marginBottom: 20, fontSize: 13 }}>
          <div style={{ fontWeight: 700, color: "#312E81", marginBottom: 8 }}>🔑 Judge Access</div>
          <div style={{ color: "#374151", lineHeight: 1.8 }}>
            <span style={{ color: "#6B7280" }}>Username:</span> <strong>apac-submission-advik</strong><br />
            <span style={{ color: "#6B7280" }}>Password:</span> <strong>APAC_Submission</strong>
          </div>
        </div>
        <SignInButton mode="modal">
          <button style={ls.signInBtn}>Sign in to your account →</button>
        </SignInButton>
        <div style={ls.features}>
          {[
            ["📄", "PDF & image extraction", "Digital text, scanned, and handwritten invoices"],
            ["✓",  "GST validation",          "GSTIN format, amount reconciliation, CGST/SGST/IGST checks"],
            ["🔒", "Full data isolation",      "RLS-backed multi-tenant — no cross-client data access ever"],
          ].map(([icon, title, desc]) => (
            <div key={title} style={ls.featureRow}>
              <span style={ls.featureIcon}>{icon}</span>
              <div>
                <div style={ls.featureTitle}>{title}</div>
                <div style={ls.featureDesc}>{desc}</div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

const ls = {
  root:         { minHeight: "100vh", background: "#312E81", display: "flex", alignItems: "center", justifyContent: "center", fontFamily: "Inter, system-ui, -apple-system, sans-serif", padding: 24 },
  panel:        { background: "#fff", borderRadius: 14, padding: "48px 44px", width: "100%", maxWidth: 420, boxShadow: "0 20px 60px rgba(0,0,0,0.25)" },
  logoWrap:     { marginBottom: 24 },
  logoMark:     { width: 44, height: 44, borderRadius: 10, background: "#312E81", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 12, fontWeight: 800, letterSpacing: "0.05em", color: "#fff" },
  heading:      { margin: "0 0 8px", fontSize: 24, fontWeight: 700, color: "#111318", letterSpacing: "-0.02em" },
  subheading:   { margin: "0 0 28px", fontSize: 14, color: "#6B7280", lineHeight: 1.6 },
  signInBtn:    { width: "100%", background: "#312E81", color: "#fff", border: "none", borderRadius: 8, padding: "12px 20px", fontSize: 14, fontWeight: 600, cursor: "pointer", fontFamily: "inherit", letterSpacing: "-0.01em", marginBottom: 32 },
  features:     { display: "flex", flexDirection: "column", gap: 16 },
  featureRow:   { display: "flex", gap: 14, alignItems: "flex-start" },
  featureIcon:  { fontSize: 18, lineHeight: 1, marginTop: 1, flexShrink: 0 },
  featureTitle: { fontSize: 13, fontWeight: 600, color: "#111318", marginBottom: 2 },
  featureDesc:  { fontSize: 12, color: "#6B7280", lineHeight: 1.5 },
};

// ── Org creation screen ───────────────────────────────────────────────────────

function CreateOrgScreen() {
  return (
    <div style={{ minHeight: "100vh", background: "#F7F8FA", display: "flex", alignItems: "center", justifyContent: "center", fontFamily: "Inter, system-ui, sans-serif", flexDirection: "column", gap: 20, padding: 24 }}>
      <div style={{ background: "#fff", border: "1px solid #E5E7EB", borderRadius: 12, padding: "32px 36px", maxWidth: 480, width: "100%" }}>
        <div style={{ fontSize: 13, color: "#6B7280", marginBottom: 16 }}>
          You're signed in, but not part of an organization yet. Create one to
          get started — this becomes your isolated workspace.
        </div>
        <CreateOrganization />
      </div>
    </div>
  );
}


// ── Top navigation ────────────────────────────────────────────────────────────

const TOP_TABS = [
  { id: "Invoices",        label: "Invoices",        icon: "📄" },
  { id: "Vendors",         label: "Vendors",         icon: "🏭" },
  { id: "Exceptions",      label: "Exceptions",      icon: "⚠" },
  { id: "ITC Summary",     label: "ITC Summary",     icon: "₹"  },
  { id: "Analytics",       label: "Analytics",       icon: "📊" },
  { id: "Activity",        label: "Activity",        icon: "🕑" },
  { id: "Settings",        label: "Settings",        icon: "⚙"  },
];

function TopNav({ activeTab, setActiveTab }) {
  return (
    <div style={ns.bar}>
      <div style={ns.left}>
        <div style={ns.logoMark}>IIS</div>
        <span style={ns.appName}>Invoice Intelligence</span>
        <nav style={ns.tabs}>
          {TOP_TABS.map(tab => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              style={{ ...ns.tab, ...(activeTab === tab.id ? ns.tabActive : ns.tabInactive) }}
            >
              {tab.label}
            </button>
          ))}
        </nav>
      </div>
      <div style={ns.right}>
        <OrganizationSwitcher
          appearance={{
            elements: {
              organizationSwitcherTrigger: {
                background: "rgba(255,255,255,0.12)",
                border: "1px solid rgba(255,255,255,0.2)",
                borderRadius: 6, color: "#fff", fontSize: 13, padding: "5px 10px",
              },
            },
          }}
        />
        <UserButton afterSignOutUrl="/" />
      </div>
    </div>
  );
}

const ns = {
  bar:         { background: "#312E81", display: "flex", alignItems: "center", justifyContent: "space-between", padding: "0 20px", height: 52, flexShrink: 0 },
  left:        { display: "flex", alignItems: "center", gap: 16 },
  right:       { display: "flex", alignItems: "center", gap: 12 },
  logoMark:    { width: 28, height: 28, borderRadius: 6, background: "rgba(255,255,255,0.15)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 9, fontWeight: 800, color: "#fff", letterSpacing: "0.05em", fontFamily: "Inter, system-ui, sans-serif" },
  appName:     { fontSize: 14, fontWeight: 600, color: "#fff", letterSpacing: "-0.01em", fontFamily: "Inter, system-ui, sans-serif" },
  tabs:        { display: "flex", gap: 2 },
  tab:         { background: "none", border: "none", cursor: "pointer", fontSize: 13, fontFamily: "Inter, system-ui, sans-serif", padding: "6px 12px", borderRadius: 6 },
  tabActive:   { background: "rgba(255,255,255,0.15)", color: "#fff", fontWeight: 600 },
  tabInactive: { color: "rgba(255,255,255,0.65)", fontWeight: 400 },
};

// ── App shell ─────────────────────────────────────────────────────────────────

function AppShell() {
  const { getToken }     = useAuth();
  const { organization } = useOrganization();
  const [activeTab,    setActiveTab]    = useState("Invoices");

  if (!organization) return <CreateOrgScreen />;

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100vh", overflow: "hidden", fontFamily: "Inter, system-ui, sans-serif" }}>
      <TopNav activeTab={activeTab} setActiveTab={setActiveTab} />
      <ErrorBoundary key={activeTab}>
        {activeTab === "Invoices"        && <InvoiceList    getToken={getToken} />}
        {activeTab === "Vendors"         && <VendorScorecard getToken={getToken} />}
        {activeTab === "Exceptions"      && <Exceptions      getToken={getToken} />}
        {activeTab === "ITC Summary"     && <ItcSummary      getToken={getToken} />}
        {activeTab === "Analytics"       && <Analytics       getToken={getToken} />}
        {activeTab === "Activity"        && <ActivityLog     getToken={getToken} />}
        {activeTab === "Settings"        && <Settings        getToken={getToken} />}
      </ErrorBoundary>
    </div>
  );
}

// ── Root ──────────────────────────────────────────────────────────────────────

export default function App() {
  return (
    <>
      <SignedOut><LoginPage /></SignedOut>
      <SignedIn><AppShell /></SignedIn>
    </>
  );
}