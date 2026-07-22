import { useState, useEffect } from 'react';
import { useAuthStore } from '../store/authStore';
import { useNavigate, Link } from 'react-router-dom';
import axios from 'axios';
import CentralizedGraphModal from '../components/CentralizedGraphModal';
import CentralizedHeatmapModal from '../components/CentralizedHeatmapModal';

type StatusFilter = 'INTAKE' | 'INVESTIGATING' | 'ACTION_TAKEN' | 'CLOSED' | 'ALL';

export default function HomePage() {
  const { accessToken: token, clearAuth } = useAuthStore();
  const navigate = useNavigate();
  const [cases, setCases] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<StatusFilter>('INTAKE');
  const [activeGlobalModal, setActiveGlobalModal] = useState<'graph' | 'map' | null>(null);

  const handleLogout = () => {
    clearAuth();
    navigate('/login');
  };

  useEffect(() => {
    const fetchCases = async () => {
      try {
        const res = await axios.get('/api/v1/investigator/cases', {
          headers: { Authorization: `Bearer ${token}` }
        });
        setCases(res.data.data?.items || res.data.items || res.data.data?.cases || res.data.cases || []);
      } catch (err) {
        console.error("Failed to fetch cases", err);
      } finally {
        setLoading(false);
      }
    };
    if (token) fetchCases();
  }, [token]);

  // SSE Real-time Updates
  useEffect(() => {
    if (!token) return;
    const eventSource = new EventSource('/api/v1/investigator/stream?token=' + token);
    
    eventSource.addEventListener('case_created', (e) => {
      try {
        const newCase = JSON.parse(e.data);
        setCases(prev => [newCase, ...prev.filter(c => c.caseId !== newCase.caseId)]);
      } catch(err) {}
    });

    eventSource.addEventListener('case_updated', (e) => {
      try {
        const updatedCase = JSON.parse(e.data);
        setCases(prev => prev.map(c => (c.caseId === updatedCase.caseId || c.id === updatedCase.caseId) ? { ...c, ...updatedCase } : c));
      } catch(err) {}
    });

    return () => eventSource.close();
  }, [token]);

  const filteredCases = cases.filter(c => {
    const st = (c.status || 'New').toUpperCase();
    if (filter === 'INTAKE') {
      return ['NEW', 'PENDING_AI'].includes(st) || !st;
    }
    if (filter === 'INVESTIGATING') {
      return ['INVESTIGATING', 'ASSIGNED', 'ELEVATED'].includes(st);
    }
    if (filter === 'ACTION_TAKEN') {
      return st === 'ACTION_TAKEN' || st === 'CONFIRMED_FRAUD';
    }
    if (filter === 'CLOSED') {
      return st === 'CLOSED' || st === 'DISMISSED';
    }
    return true; // ALL
  });

  const intakeCount = cases.filter(c => ['NEW', 'PENDING_AI'].includes((c.status || 'NEW').toUpperCase())).length;
  const investigatingCount = cases.filter(c => ['INVESTIGATING', 'ASSIGNED', 'ELEVATED'].includes((c.status || '').toUpperCase())).length;
  const actionTakenCount = cases.filter(c => (c.status || '').toUpperCase() === 'ACTION_TAKEN' || (c.status || '').toUpperCase() === 'CONFIRMED_FRAUD').length;
  const closedCount = cases.filter(c => (c.status || '').toUpperCase() === 'CLOSED' || (c.status || '').toUpperCase() === 'DISMISSED').length;

  return (
    <div className="min-h-screen bg-slate-900 text-slate-200">
      <header className="bg-slate-800 border-b border-slate-700 p-4 flex justify-between items-center shadow-lg sticky top-0 z-10">
        <h1 className="text-2xl font-bold text-white flex items-center gap-2">
          <span className="bg-blue-600 text-white w-8 h-8 rounded-lg flex items-center justify-center font-mono">I</span>
          Investigator Dashboard
        </h1>
        
        <div className="flex items-center gap-3">
          <button
            onClick={() => setActiveGlobalModal('graph')}
            className="bg-indigo-600/90 hover:bg-indigo-500 text-white px-3.5 py-2 rounded-lg font-semibold transition-all text-xs flex items-center gap-2 border border-indigo-500/30 shadow-md"
          >
            <span>🕸️ Centralized Syndicate Graph</span>
          </button>

          <button
            onClick={() => setActiveGlobalModal('map')}
            className="bg-red-600/90 hover:bg-red-500 text-white px-3.5 py-2 rounded-lg font-semibold transition-all text-xs flex items-center gap-2 border border-red-500/30 shadow-md"
          >
            <span>🗺️ National Fraud Heatmap</span>
          </button>

          <button onClick={handleLogout} className="bg-slate-700 hover:bg-slate-600 text-white px-4 py-2 rounded-lg font-medium transition-colors text-xs">
            Sign Out
          </button>
        </div>
      </header>

      <main className="container mx-auto px-4 py-8 max-w-6xl">
        <div className="flex flex-col md:flex-row justify-between items-start md:items-end gap-4 mb-6">
          <div>
            <h2 className="text-xl font-bold text-white">Case Lifecycle Management</h2>
            <p className="text-slate-400 text-sm">Track cyber fraud cases across all 4 operational lifecycle stages</p>
          </div>
          <div className="flex items-center gap-3">
            <div className="bg-slate-800 px-3 py-1.5 rounded-lg text-xs border border-slate-700 flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse"></span>
              <span className="text-slate-300 font-medium">SSE Stream Live</span>
            </div>
          </div>
        </div>

        {/* 4 Section Filter Tabs */}
        <div className="flex flex-wrap gap-2 mb-6 border-b border-slate-800 pb-3">
          <button
            onClick={() => setFilter('INTAKE')}
            className={`px-4 py-2 rounded-xl text-sm font-semibold transition-all flex items-center gap-2 ${
              filter === 'INTAKE'
                ? 'bg-blue-600 text-white shadow-lg shadow-blue-500/20'
                : 'bg-slate-800 text-slate-400 hover:text-white border border-slate-700'
            }`}
          >
            <span>⚡ 1. Case Registered</span>
            <span className="px-2 py-0.5 rounded-full text-xs bg-blue-900/60 text-blue-200">{intakeCount}</span>
          </button>

          <button
            onClick={() => setFilter('INVESTIGATING')}
            className={`px-4 py-2 rounded-xl text-sm font-semibold transition-all flex items-center gap-2 ${
              filter === 'INVESTIGATING'
                ? 'bg-amber-600 text-white shadow-lg shadow-amber-500/20'
                : 'bg-slate-800 text-slate-400 hover:text-white border border-slate-700'
            }`}
          >
            <span>🔍 2. Under Investigation</span>
            <span className="px-2 py-0.5 rounded-full text-xs bg-amber-900/60 text-amber-200">{investigatingCount}</span>
          </button>

          <button
            onClick={() => setFilter('ACTION_TAKEN')}
            className={`px-4 py-2 rounded-xl text-sm font-semibold transition-all flex items-center gap-2 ${
              filter === 'ACTION_TAKEN'
                ? 'bg-emerald-600 text-white shadow-lg shadow-emerald-500/20'
                : 'bg-slate-800 text-slate-400 hover:text-white border border-slate-700'
            }`}
          >
            <span>🚨 3. Confirmed Fraud (Action Taken)</span>
            <span className="px-2 py-0.5 rounded-full text-xs bg-emerald-900/60 text-emerald-200">{actionTakenCount}</span>
          </button>

          <button
            onClick={() => setFilter('CLOSED')}
            className={`px-4 py-2 rounded-xl text-sm font-semibold transition-all flex items-center gap-2 ${
              filter === 'CLOSED'
                ? 'bg-slate-700 text-white shadow-lg'
                : 'bg-slate-800 text-slate-400 hover:text-white border border-slate-700'
            }`}
          >
            <span>📁 4. Closed Case</span>
            <span className="px-2 py-0.5 rounded-full text-xs bg-slate-900 text-slate-300">{closedCount}</span>
          </button>

          <button
            onClick={() => setFilter('ALL')}
            className={`px-4 py-2 rounded-xl text-sm font-semibold transition-all flex items-center gap-2 ${
              filter === 'ALL'
                ? 'bg-purple-600 text-white shadow-lg shadow-purple-500/20'
                : 'bg-slate-800 text-slate-400 hover:text-white border border-slate-700'
            }`}
          >
            <span>🌐 All Cases</span>
            <span className="px-2 py-0.5 rounded-full text-xs bg-purple-900/60 text-purple-200">{cases.length}</span>
          </button>
        </div>

        {/* Case List Grid */}
        {loading ? (
          <div className="flex justify-center items-center h-64">
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500"></div>
          </div>
        ) : filteredCases.length === 0 ? (
          <div className="bg-slate-800 rounded-2xl p-12 text-center border border-slate-700">
            <p className="text-slate-400 text-lg">No cases in this stage.</p>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {filteredCases.map((c) => {
              const caseId = c.caseId || c.case_id || c.id || c.caseNumber || c.case_number;
              const st = (c.status || 'New').toUpperCase();
              return (
                <div key={caseId} className="bg-slate-800 border border-slate-700 rounded-2xl p-6 shadow-xl flex flex-col justify-between hover:border-slate-500 transition-all">
                  <div>
                    <div className="flex justify-between items-start mb-4">
                      <span className="text-xs font-mono bg-slate-900 text-blue-400 px-2.5 py-1 rounded-md border border-slate-700">
                        #{c.caseNumber || c.case_number || (caseId && caseId.length >= 8 ? caseId.substring(0, 8) : caseId || 'N/A')}
                      </span>
                      <span className={`px-2.5 py-0.5 rounded-full text-xs font-bold ${
                        st === 'INVESTIGATING' ? 'bg-amber-500/20 text-amber-400 border border-amber-500/30' :
                        st === 'ACTION_TAKEN' || st === 'CONFIRMED_FRAUD' ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30' :
                        st === 'CLOSED' ? 'bg-slate-700 text-slate-300' : 'bg-blue-500/20 text-blue-400 border border-blue-500/30'
                      }`}>
                        {st}
                      </span>
                    </div>
                    <h3 className="text-lg font-bold text-white mb-2 line-clamp-1">{c.title}</h3>
                    <p className="text-slate-400 text-sm mb-4 line-clamp-2">{c.description}</p>
                  </div>
                  
                  <div className="pt-4 border-t border-slate-700 flex justify-between items-center">
                    <span className="text-xs text-slate-500">{c.complaintType || 'UPI_FRAUD'}</span>
                    <Link
                      to={`/cases/${caseId}`}
                      className="bg-blue-600 hover:bg-blue-500 text-white text-xs font-bold px-3 py-1.5 rounded-lg transition-colors"
                    >
                      Investigate →
                    </Link>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </main>

      {/* Global Centralized Syndicate Graph Modal */}
      {activeGlobalModal === 'graph' && (
        <CentralizedGraphModal onClose={() => setActiveGlobalModal(null)} />
      )}

      {/* Global Centralized National Heatmap Modal */}
      {activeGlobalModal === 'map' && (
        <CentralizedHeatmapModal cases={cases} onClose={() => setActiveGlobalModal(null)} />
      )}
    </div>
  );
}
