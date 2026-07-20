import { useState, useEffect } from 'react';
import { useAuthStore } from '../store/authStore';
import { useNavigate, Link } from 'react-router-dom';
import axios from 'axios';

export default function HomePage() {
  const { accessToken: token, clearAuth } = useAuthStore();
  const navigate = useNavigate();
  const [cases, setCases] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

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
        setCases(res.data.items || []);
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
        setCases(prev => prev.map(c => c.caseId === updatedCase.caseId ? { ...c, ...updatedCase } : c));
      } catch(err) {}
    });

    return () => eventSource.close();
  }, [token]);

  return (
    <div className="min-h-screen bg-slate-900 text-slate-200">
      <header className="bg-slate-800 border-b border-slate-700 p-4 flex justify-between items-center shadow-lg">
        <h1 className="text-2xl font-bold text-white flex items-center gap-2">
          <span className="bg-blue-600 text-white w-8 h-8 rounded-lg flex items-center justify-center">I</span>
          Investigator Dashboard
        </h1>
        <button onClick={handleLogout} className="bg-slate-700 hover:bg-slate-600 text-white px-4 py-2 rounded-lg font-medium transition-colors">
          Sign Out
        </button>
      </header>

      <main className="container mx-auto px-4 py-8 max-w-6xl">
        <div className="flex justify-between items-end mb-6">
          <div>
            <h2 className="text-xl font-bold text-white">Active Case Queue</h2>
            <p className="text-slate-400 text-sm">Real-time incoming fraud cases requiring review</p>
          </div>
          <div className="bg-slate-800 px-4 py-2 rounded-lg text-sm border border-slate-700">
            <span className="text-green-400 font-bold mr-2">● Live</span> Connected
          </div>
        </div>

        {loading ? (
          <div className="flex justify-center py-20"><div className="animate-spin rounded-full h-12 w-12 border-b-2 border-white"></div></div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {cases.length === 0 ? (
              <div className="col-span-full text-center py-16 text-slate-500 bg-slate-800/50 rounded-2xl border border-slate-700 border-dashed">
                No active cases in your jurisdiction.
              </div>
            ) : (
              cases.map((c) => (
                <Link to={`/cases/${c.caseId || c.id}`} key={c.caseId || c.id} className="block group">
                  <div className="bg-slate-800 rounded-2xl p-6 border border-slate-700 shadow-xl group-hover:border-blue-500/50 transition-all">
                    <div className="flex justify-between items-start mb-4">
                      <span className={`px-3 py-1 rounded-full text-xs font-bold tracking-wider ${
                        c.riskTier === 'CRITICAL' ? 'bg-red-500/20 text-red-400 border border-red-500/30' :
                        c.riskTier === 'HIGH' ? 'bg-orange-500/20 text-orange-400 border border-orange-500/30' :
                        'bg-yellow-500/20 text-yellow-400 border border-yellow-500/30'
                      }`}>
                        {c.riskTier || 'PENDING'}
                      </span>
                      <span className="text-slate-500 text-xs">{new Date(c.timestamp || Date.now()).toLocaleDateString()}</span>
                    </div>
                    <h3 className="text-lg font-bold text-white mb-1 truncate">{c.complaintType?.replace('_', ' ') || 'Fraud Case'}</h3>
                    <p className="text-slate-400 text-sm mb-4 truncate">Case #{c.caseId?.substring(0,8) || c.id?.substring(0,8)}</p>
                    
                    <div className="bg-slate-900/50 p-3 rounded-lg border border-slate-700 mb-4">
                      <div className="flex justify-between items-center mb-1 text-sm">
                        <span className="text-slate-500">AI Confidence</span>
                        <span className="text-white font-medium">{c.fusedScore || c.confidence || 0}%</span>
                      </div>
                      <div className="w-full bg-slate-800 rounded-full h-1.5">
                        <div className={`h-1.5 rounded-full ${c.fusedScore > 80 ? 'bg-red-500' : c.fusedScore > 60 ? 'bg-orange-500' : 'bg-blue-500'}`} style={{ width: `${c.fusedScore || c.confidence || 0}%` }}></div>
                      </div>
                    </div>
                    
                    <div className="text-blue-400 text-sm font-medium flex items-center group-hover:text-blue-300 transition-colors">
                      Review Case
                      <svg className="w-4 h-4 ml-1 group-hover:translate-x-1 transition-transform" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 5l7 7-7 7"></path></svg>
                    </div>
                  </div>
                </Link>
              ))
            )}
          </div>
        )}
      </main>
    </div>
  );
}
