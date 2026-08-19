import { useState, Component } from "react";
import { useEffect } from "react";
import {
  SignedIn,
  SignedOut,
  SignInButton,
  UserButton,
  useAuth,
  useOrganization,
  useOrganizationList,
  OrganizationSwitcher,
  CreateOrganization,
} from "@clerk/clerk-react";
import InvoiceList from "./modules/InvoiceList";
import Settings from "./modules/Settings";
import ActivityLog from "./modules/ActivityLog";
import ItcSummary from "./modules/Itcsummary";
import Analytics from "./modules/Analytics";
import VendorScorecard from "./modules/VendorScorecard";
import DocumentVault from "./modules/DocumentVault";

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
        <div
          style={{
            flex: 1,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            background: "#F8FAFC",
            fontFamily: "Inter, system-ui, sans-serif",
          }}
        >
          <div
            style={{
              background: "#fff",
              border: "1px solid #FECACA",
              borderRadius: 12,
              padding: "32px 36px",
              maxWidth: 420,
              textAlign: "center",
              boxShadow: "0 4px 6px -1px rgba(0, 0, 0, 0.05)",
            }}
          >
            <div style={{ fontSize: 28, marginBottom: 12 }}>⚠️</div>
            <div
              style={{
                fontSize: 14,
                fontWeight: 700,
                color: "#E11D48",
                marginBottom: 8,
              }}
            >
              This tab ran into an error
            </div>
            <div
              style={{
                fontSize: 12,
                color: "#64748B",
                marginBottom: 16,
                lineHeight: 1.6,
              }}
            >
              {String(this.state.error)}
            </div>
            <button
              onClick={() => this.setState({ error: null })}
              style={{
                background: "#0F172A",
                color: "#fff",
                border: "none",
                borderRadius: 8,
                padding: "8px 18px",
                fontSize: 13,
                cursor: "pointer",
                fontFamily: "inherit",
                fontWeight: 600,
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
        <div
          style={{
            background: "#F8FAFC",
            border: "1px solid #E2E8F0",
            borderRadius: 8,
            padding: "14px 16px",
            marginBottom: 20,
            fontSize: 13,
          }}
        >
          <div style={{ fontWeight: 700, color: "#0F172A", marginBottom: 6 }}>
            🔑 Judge Access
          </div>
          <div style={{ color: "#475569", lineHeight: 1.8 }}>
            <span style={{ color: "#64748B" }}>Username:</span>{" "}
            <strong>apac-submission-advik</strong>
            <br />
            <span style={{ color: "#64748B" }}>Password:</span>{" "}
            <strong>APAC_Submission</strong>
          </div>
        </div>
        <SignInButton mode="modal">
          <button style={ls.signInBtn}>Sign in to your account →</button>
        </SignInButton>
        <div style={ls.features}>
          {[
            [
              "📄",
              "PDF & image extraction",
              "Digital text, scanned, and handwritten invoices",
            ],
            [
              "✓",
              "GST validation",
              "GSTIN format, amount reconciliation, CGST/SGST/IGST checks",
            ],
            [
              "🔒",
              "Full data isolation",
              "RLS-backed multi-tenant — no cross-client data access ever",
            ],
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
  root: {
    minHeight: "100vh",
    background: "#0F172A", // Professional deep slate
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    fontFamily: "Inter, system-ui, -apple-system, sans-serif",
    padding: 24,
  },
  panel: {
    background: "#fff",
    borderRadius: 14,
    padding: "48px 44px",
    width: "100%",
    maxWidth: 420,
    boxShadow:
      "0 20px 25px -5px rgba(0, 0, 0, 0.1), 0 10px 10px -5px rgba(0, 0, 0, 0.04)",
  },
  logoWrap: { marginBottom: 24 },
  logoMark: {
    width: 44,
    height: 44,
    borderRadius: 10,
    background: "#0F172A",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    fontSize: 14,
    fontWeight: 800,
    letterSpacing: "0.05em",
    color: "#fff",
  },
  heading: {
    margin: "0 0 8px",
    fontSize: 24,
    fontWeight: 700,
    color: "#0F172A",
    letterSpacing: "-0.02em",
  },
  subheading: {
    margin: "0 0 24px",
    fontSize: 14,
    color: "#64748B",
    lineHeight: 1.6,
  },
  signInBtn: {
    width: "100%",
    background: "#4F46E5", // Modern Fintech Indigo
    color: "#fff",
    border: "none",
    borderRadius: 8,
    padding: "12px 20px",
    fontSize: 14,
    fontWeight: 600,
    cursor: "pointer",
    fontFamily: "inherit",
    letterSpacing: "-0.01em",
    marginBottom: 28,
    boxShadow: "0 1px 2px 0 rgba(0, 0, 0, 0.05)",
  },
  features: { display: "flex", flexDirection: "column", gap: 16 },
  featureRow: { display: "flex", gap: 14, alignItems: "flex-start" },
  featureIcon: { fontSize: 18, lineHeight: 1, marginTop: 1, flexShrink: 0 },
  featureTitle: {
    fontSize: 13,
    fontWeight: 600,
    color: "#0F172A",
    marginBottom: 2,
  },
  featureDesc: { fontSize: 12, color: "#64748B", lineHeight: 1.5 },
};

function CreateOrgScreen() {
  return (
    <div
      style={{
        minHeight: "100vh",
        background: "#F8FAFC",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        fontFamily: "Inter, system-ui, sans-serif",
        flexDirection: "column",
        gap: 20,
        padding: 24,
      }}
    >
      <div
        style={{
          background: "#fff",
          border: "1px solid #E2E8F0",
          borderRadius: 12,
          padding: "32px 36px",
          maxWidth: 480,
          width: "100%",
          boxShadow: "0 4px 6px -1px rgba(0, 0, 0, 0.05)",
        }}
      >
        <div
          style={{
            fontSize: 13,
            color: "#475569",
            marginBottom: 16,
            lineHeight: 1.6,
          }}
        >
          You're signed in, but not part of an organization yet. Create one to
          get started — this becomes your isolated workspace.
        </div>
        <CreateOrganization />
      </div>
    </div>
  );
}

const TOP_TABS = [
  { id: "Invoices", label: "Invoices", icon: "📄" },
  { id: "Vendors", label: "Vendors", icon: "🏭" },
  { id: "Exceptions", label: "Document Vault", icon: "📂" },
  { id: "ITC Summary", label: "ITC Summary", icon: "₹" },
  { id: "Analytics", label: "Analytics", icon: "📊" },
  { id: "Activity", label: "Activity", icon: "🕑" },
  { id: "Settings", label: "Settings", icon: "⚙" },
];

function TopNav({ activeTab, setActiveTab }) {
  return (
    <div style={ns.bar}>
      <div style={ns.left}>
        <div style={ns.logoMark}>IIS</div>
        <span style={ns.appName}>Invoice Intelligence</span>
        <nav style={ns.tabs}>
          {TOP_TABS.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              style={{
                ...ns.tab,
                ...(activeTab === tab.id ? ns.tabActive : ns.tabInactive),
              }}
            >
              <span style={{ marginRight: 6 }}>{tab.icon}</span>
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
                background: "#F1F5F9",
                border: "1px solid #CBD5E1",
                borderRadius: 6,
                color: "#0F172A",
                fontSize: 13,
                padding: "5px 10px",
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
  bar: {
    background: "#FFFFFF", // Clean modern enterprise white instead of heavy dark purple
    borderBottom: "1px solid #E2E8F0",
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    padding: "0 20px",
    height: 56,
    flexShrink: 0,
  },
  left: { display: "flex", alignItems: "center", gap: 20 },
  right: { display: "flex", alignItems: "center", gap: 12 },
  logoMark: {
    width: 30,
    height: 30,
    borderRadius: 6,
    background: "#0F172A",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    fontSize: 10,
    fontWeight: 800,
    color: "#fff",
    letterSpacing: "0.05em",
    fontFamily: "Inter, system-ui, sans-serif",
  },
  appName: {
    fontSize: 14,
    fontWeight: 700,
    color: "#0F172A",
    letterSpacing: "-0.01em",
    fontFamily: "Inter, system-ui, sans-serif",
  },
  tabs: { display: "flex", gap: 4 },
  tab: {
    background: "none",
    border: "none",
    cursor: "pointer",
    fontSize: 13,
    fontFamily: "Inter, system-ui, sans-serif",
    padding: "6px 12px",
    borderRadius: 6,
    display: "flex",
    alignItems: "center",
    transition: "all 0.15s ease",
  },
  tabActive: {
    background: "#EEF2FF", // Subtle soft indigo highlight
    color: "#4F46E5",
    fontWeight: 600,
  },
  tabInactive: {
    color: "#64748B",
    fontWeight: 500,
  },
};

function AppShell() {
  const { getToken } = useAuth();
  const { organization } = useOrganization();
  const { userMemberships, setActive, isLoaded } = useOrganizationList({
    userMemberships: { infinite: true },
  });
  const [activeTab, setActiveTab] = useState("Invoices");

  useEffect(() => {
    if (!isLoaded || organization) return;
    const memberships = userMemberships?.data ?? [];
    if (memberships.length > 0 && setActive) {
      setActive({ organization: memberships[0].organization });
    }
  }, [isLoaded, organization, userMemberships, setActive]);

  const memberships = userMemberships?.data ?? [];
  const noMemberships = isLoaded && memberships.length === 0;

  if (!organization) {
    if (!isLoaded || !noMemberships) {
      return (
        <div
          style={{
            minHeight: "100vh",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            background: "#F8FAFC",
            fontFamily: "Inter, system-ui, sans-serif",
            color: "#64748B",
            fontSize: 14,
          }}
        >
          Loading workspace…
        </div>
      );
    }
    return <CreateOrgScreen />;
  }

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        height: "100vh",
        overflow: "hidden",
        fontFamily: "Inter, system-ui, sans-serif",
        background: "#F8FAFC", // Clean, modern canvas background
      }}
    >
      <TopNav activeTab={activeTab} setActiveTab={setActiveTab} />
      <div
        style={{
          flex: 1,
          overflowY: "auto",
          display: "flex",
          flexDirection: "column",
        }}
      >
        <ErrorBoundary key={activeTab}>
          {activeTab === "Invoices" && <InvoiceList getToken={getToken} />}
          {activeTab === "Vendors" && <VendorScorecard getToken={getToken} />}
          {activeTab === "Exceptions" && <DocumentVault />}
          {activeTab === "ITC Summary" && <ItcSummary getToken={getToken} />}
          {activeTab === "Analytics" && <Analytics getToken={getToken} />}
          {activeTab === "Activity" && <ActivityLog getToken={getToken} />}
          {activeTab === "Settings" && <Settings getToken={getToken} />}
        </ErrorBoundary>
      </div>
    </div>
  );
}

export default function App() {
  return (
    <>
      <SignedOut>
        <LoginPage />
      </SignedOut>
      <SignedIn>
        <AppShell />
      </SignedIn>
    </>
  );
}
