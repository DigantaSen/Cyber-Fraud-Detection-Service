import { useState, useEffect } from 'react';
import { useAuthStore } from '../store/authStore';
import { useNavigate } from 'react-router-dom';
import axios from 'axios';

export default function HomePage() {
  const { token, clearAuth } = useAuthStore();
  const navigate = useNavigate();
  
  const [alerts, setAlerts] = useState<any[]>([]);
  const [reports, setReports] = useState<any[]>([]);
  const [activeTab, setActiveTab] = useState<'alerts' | 'reports'>('alerts');
  const [loading, setLoading] = useState(true);

  const handleLogout = () => {
    clearAuth();
    navigate('/login');
  };

  useEffect(() => {
    const fetchAlerts = async () => {
      try {
        const res = await axios.get('/api/v1/gov/alerts', {
          headers: { Authorization: `Bearer ${token}` }
        });
        setAlerts(res.data.items || []);
      } catch (err) {
        console.error("Failed to fetch alerts", err);
      }
    };

    const fetchReports = async () => {
      try {
        const res = await axios.get('/api/v1/gov/reports', {
          headers: { Authorization: `Bearer ${token}` }
        });
        setReports(res.data.items || []);
      } catch (err) {
        console.error("Failed to fetch reports", err);
      }
    };

    if (token) {
      setLoading(true);
      Promise.all([fetchAlerts(), fetchReports()]).finally(() => setLoading(false));
    }
  }, [token]);

  // Setup SSE for real-time alerts
  useEffect(() => {
    if (!token) return;
    
    const eventSource = new EventSource('/api/v1/gov/stream?token=' + token);
    
    eventSource.addEventListener('mha_alert', (e) => {
      try {
        const data = JSON.parse(e.data);
        setAlerts(prev => [data, ...prev]);
      } catch (err) {
        console.error(err);
      }
    });

    return () => eventSource.close();
  }, [token]);

  return (
    <div className="min-h-screen bg-slate-900 text-slate-100 flex flex-col">
      <header className="bg-slate-800 border-b border-slate-700 p-4 flex justify-between items-center shadow-md">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-full bg-red-600 flex items-center justify-center text-white font-bold shadow-[0_0_15px_rgba(220,38,38,0.6)]">
            MHA
          </div>
          <h1 className="text-xl font-bold tracking-wide">National Cyber Command Center</h1>
        </div>
        <button 
          onClick={handleLogout} 
          className="bg-slate-700 hover:bg-slate-600 text-slate-200 px-4 py-2 rounded-lg font-medium transition-colors"
        >
          Sign Out
        </button>
      </header>

      <main className="flex-1 container mx-auto px-4 py-8 max-w-6xl">
        <div className="flex gap-4 mb-8">
          <button 
            onClick={() => setActiveTab('alerts')}
            className={`px-6 py-3 rounded-lg font-semibold transition-all duration-300 ${activeTab === 'alerts' ? 'bg-red-600 text-white shadow-[0_0_20px_rgba(220,38,38,0.4)]' : 'bg-slate-800 text-slate-400 hover:bg-slate-700'}`}
          >
            Live MHA Alerts
          </button>
          <button 
            onClick={() => setActiveTab('reports')}
            className={`px-6 py-3 rounded-lg font-semibold transition-all duration-300 ${activeTab === 'reports' ? 'bg-indigo-600 text-white shadow-[0_0_20px_rgba(79,70,229,0.4)]' : 'bg-slate-800 text-slate-400 hover:bg-slate-700'}`}
          >
            Intelligence Packages
          </button>
        </div>

        {loading ? (
          <div className="flex justify-center py-20">
            <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-white"></div>
          </div>
        ) : activeTab === 'alerts' ? (
          <div className="space-y-4">
            {alerts.length === 0 ? (
              <div className="text-center py-12 text-slate-500 bg-slate-800/50 rounded-xl border border-slate-700/50">
                No active critical alerts
              </div>
            ) : (
              alerts.map((alert, idx) => (
                <div key={idx} className="bg-slate-800 rounded-xl p-6 border border-red-900/30 shadow-lg relative overflow-hidden group">
                  <div className="absolute top-0 left-0 w-1 h-full bg-gradient-to-b from-red-500 to-orange-500"></div>
                  
                  <div className="flex justify-between items-start mb-4">
                    <div className="flex items-center gap-3">
                      <span className="bg-red-500/20 text-red-400 px-3 py-1 rounded-full text-xs font-bold tracking-wider border border-red-500/30">
                        {alert.riskTier || 'CRITICAL'}
                      </span>
                      <span className="text-slate-400 text-sm">ID: {alert.alertId}</span>
                    </div>
                    <div className="text-slate-400 text-sm">{new Date(alert.dispatchedAt || Date.now()).toLocaleString()}</div>
                  </div>
                  
                  <h3 className="text-xl font-bold text-white mb-2">{alert.alertType || 'FRAUD_RING_DETECTED'}</h3>
                  <p className="text-slate-300 mb-4 text-lg">{alert.summary}</p>
                  
                  <div className="flex flex-wrap gap-4 text-sm">
                    <div className="bg-slate-900/50 px-4 py-2 rounded-lg border border-slate-700">
                      <span className="text-slate-500 mr-2">Jurisdiction:</span>
                      <span className="text-slate-200 font-medium">{alert.jurisdictionId}</span>
                    </div>
                    {alert.suspects && alert.suspects.length > 0 && (
                      <div className="bg-slate-900/50 px-4 py-2 rounded-lg border border-slate-700">
                        <span className="text-slate-500 mr-2">Suspects:</span>
                        <span className="text-slate-200 font-medium">{alert.suspects.join(', ')}</span>
                      </div>
                    )}
                  </div>
                </div>
              ))
            )}
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {reports.length === 0 ? (
              <div className="col-span-full text-center py-12 text-slate-500 bg-slate-800/50 rounded-xl border border-slate-700/50">
                No intelligence packages generated yet
              </div>
            ) : (
              reports.map((report, idx) => (
                <div key={idx} className="bg-slate-800 rounded-xl p-6 border border-indigo-900/30 shadow-lg hover:shadow-[0_0_30px_rgba(79,70,229,0.15)] transition-all group">
                  <div className="flex justify-between items-center mb-4">
                    <div className="w-12 h-12 rounded-lg bg-indigo-500/20 text-indigo-400 flex items-center justify-center border border-indigo-500/30">
                      <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 17v-2m3 2v-4m3 4v-6m2 10H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"></path></svg>
                    </div>
                    <span className="text-slate-400 text-xs">{new Date(report.generatedAt || Date.now()).toLocaleDateString()}</span>
                  </div>
                  <h3 className="text-lg font-bold text-white mb-1">Case {report.caseId}</h3>
                  <p className="text-indigo-300 text-sm font-medium mb-4">{report.reportType}</p>
                  
                  <div className="text-slate-400 text-sm mb-6 flex items-center gap-2">
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"></path></svg>
                    <span>{report.investigatorId || 'System'}</span>
                  </div>
                  
                  <a href={report.downloadUrl || '#'} className="block w-full py-2.5 text-center bg-indigo-600 hover:bg-indigo-500 text-white font-medium rounded-lg transition-colors">
                    Download Package
                  </a>
                </div>
              ))
            )}
          </div>
        )}
      </main>
    </div>
  );
}
