const { useState, useEffect } = React;

// --- Mock Data ---
const MOCK_ALERTS = [
  {
    alertId: "alrt-1a2b3c",
    alertType: "FRAUD_RING_DETECTED",
    riskTier: "CRITICAL",
    summary: "Detected active fraud ring of 7 nodes operating across multiple banks.",
    jurisdictionId: "JUR_MH_MUMBAI",
    suspects: ["+919876543210", "+919876543211"],
    dispatchedAt: new Date(Date.now() - 1000 * 60 * 5).toISOString(), // 5 mins ago
  },
  {
    alertId: "alrt-4d5e6f",
    alertType: "HIGH_VALUE_EXFILTRATION",
    riskTier: "CRITICAL",
    summary: "Large scale UPI exfiltration attempt detected. Total value exceeds ₹50,000,000.",
    jurisdictionId: "JUR_DL_NEWDELHI",
    suspects: ["+918000000001"],
    dispatchedAt: new Date(Date.now() - 1000 * 60 * 15).toISOString(),
  },
  {
    alertId: "alrt-7g8h9i",
    alertType: "NEW_SCAM_PATTERN",
    riskTier: "HIGH",
    summary: "New conversational scam pattern detected targeting elderly demographics.",
    jurisdictionId: "NATIONAL",
    suspects: ["Unknown Group"],
    dispatchedAt: new Date(Date.now() - 1000 * 60 * 60 * 2).toISOString(),
  }
];

const MOCK_REPORTS = [
  {
    id: "rep-001",
    title: "Weekly National Fraud Topology",
    date: "2026-07-18",
    type: "NCRB_STANDARD",
    status: "AVAILABLE"
  },
  {
    id: "rep-002",
    title: "Intelligence Package: Mumbai Syndicate Alpha",
    date: "2026-07-17",
    type: "INTELLIGENCE_PKG",
    status: "AVAILABLE"
  }
];

// --- Components ---

function Sidebar({ currentView, setCurrentView }) {
  return (
    <div className="sidebar">
      <div className="sidebar-brand">
        <i data-lucide="shield-alert" style={{ color: "var(--accent-primary)" }}></i>
        MHA Cyber Portal
      </div>
      <nav className="nav-menu">
        <a 
          className={`nav-item ${currentView === 'alerts' ? 'active' : ''}`}
          onClick={() => setCurrentView('alerts')}
        >
          <i data-lucide="bell"></i> Live Alerts
        </a>
        <a 
          className={`nav-item ${currentView === 'reports' ? 'active' : ''}`}
          onClick={() => setCurrentView('reports')}
        >
          <i data-lucide="file-text"></i> NCRB Reports
        </a>
      </nav>
    </div>
  );
}

function Header() {
  return (
    <header className="header">
      <div>
        <h1>National Cyber Command Center</h1>
      </div>
      <div className="header-user">
        <span>Gov Official (Super Admin)</span>
        <div className="user-avatar">GO</div>
      </div>
    </header>
  );
}

function AlertsView() {
  const [alerts, setAlerts] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // Simulate API fetch GET /gov/alerts
    setTimeout(() => {
      setAlerts(MOCK_ALERTS);
      setLoading(false);
      // Re-initialize icons after content renders
      setTimeout(() => lucide.createIcons(), 0);
    }, 600);
  }, []);

  return (
    <div className="view-container">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.5rem' }}>
        <h2>High-Priority MHA Alerts</h2>
        <button className="btn btn-outline">
          <i data-lucide="filter" size="16"></i> Filter
        </button>
      </div>

      {loading ? (
        <div>Loading alerts...</div>
      ) : (
        <div className="alerts-grid">
          {alerts.map(alert => (
            <div key={alert.alertId} className={`alert-card tier-${alert.riskTier}`}>
              <div className="alert-header">
                <span className="alert-type">{alert.alertType.replace(/_/g, ' ')}</span>
                <span className={`badge tier-${alert.riskTier}`}>{alert.riskTier}</span>
              </div>
              <p className="alert-summary">{alert.summary}</p>
              
              <div className="alert-meta">
                <div className="meta-row">
                  <i data-lucide="map-pin" size="14"></i>
                  <span>Jurisdiction: {alert.jurisdictionId}</span>
                </div>
                <div className="meta-row">
                  <i data-lucide="clock" size="14"></i>
                  <span>Dispatched: {new Date(alert.dispatchedAt).toLocaleTimeString()}</span>
                </div>
                <div className="meta-row">
                  <i data-lucide="users" size="14"></i>
                  <span>Suspects: {alert.suspects.join(", ")}</span>
                </div>
              </div>
              
              <div style={{ marginTop: '1.5rem', display: 'flex', gap: '0.5rem' }}>
                <button className="btn" style={{ flex: 1 }}>View Details</button>
                <button className="btn btn-outline"><i data-lucide="share-2" size="16"></i></button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function ReportsView() {
  const [reports, setReports] = useState([]);

  useEffect(() => {
    setReports(MOCK_REPORTS);
    setTimeout(() => lucide.createIcons(), 0);
  }, []);

  const handleRequestPackage = () => {
    alert("Requesting new intelligence package... (POST /gov/reports/intelligence-package)");
  };

  return (
    <div className="view-container">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.5rem' }}>
        <h2>NCRB Reports & Intelligence</h2>
        <button className="btn" onClick={handleRequestPackage}>
          <i data-lucide="plus" size="16"></i> Request Intel Package
        </button>
      </div>

      <div className="reports-list">
        {reports.map(rep => (
          <div key={rep.id} className="report-item">
            <div className="report-info">
              <h3>{rep.title}</h3>
              <p>Type: {rep.type} | Date: {rep.date}</p>
            </div>
            <div>
              <button className="btn btn-outline">Download PDF</button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function App() {
  const [currentView, setCurrentView] = useState('alerts');

  return (
    <div className="dashboard-layout">
      <Sidebar currentView={currentView} setCurrentView={setCurrentView} />
      <main className="main-content">
        <Header />
        {currentView === 'alerts' ? <AlertsView /> : <ReportsView />}
      </main>
    </div>
  );
}

const root = ReactDOM.createRoot(document.getElementById('root'));
root.render(<App />);
